from leave.locking import locked_employee_sync
"""Synchronise paid sick leave balances with MOM's linked annual limits."""

from datetime import date, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from employee.models import EmployeeWorkInformation
from leave.annual_entitlement import add_months
from leave.methods import calculate_requested_days
from leave.models import cal_effective_requested_days
from leave.sick_entitlement import calculate_sick_entitlement


def entitlement_for_assignment(assignment, as_of=None):
    work_info = EmployeeWorkInformation.objects.filter(
        employee_id=assignment.employee_id
    ).first()
    if not work_info or not work_info.date_joining:
        return None
    return calculate_sick_entitlement(
        work_info.date_joining,
        as_of or timezone.localdate(),
        policy=assignment.leave_type_id.auto_leave_policy,
        configured_days=int(assignment.leave_type_id.total_days or 0),
        employment_end_date=work_info.contract_end_date,
    )


def approved_sick_days(assignment, entitlement, as_of=None):
    """Outpatient use reduces both balances; hospital use reduces the shared cap."""
    from leave.models import LeaveRequest

    as_of = as_of or timezone.localdate()
    join_date = assignment.employee_id.employee_work_info.date_joining
    period_end = (
        add_months(join_date, 6) - timedelta(days=1)
        if entitlement.completed_months < 6
        else date(entitlement.usage_start.year, 12, 31)
    )
    policies = ["outpatient_sick"]
    if assignment.leave_type_id.auto_leave_policy == "hospitalisation":
        policies.append("hospitalisation")
    requests = LeaveRequest.objects.filter(
        Q(end_date__gte=entitlement.usage_start) | Q(end_date__isnull=True),
        employee_id=assignment.employee_id,
        leave_type_id__auto_leave_policy__in=policies,
        status="approved",
        start_date__lte=period_end,
    ).select_related("leave_type_id")
    days = 0.0
    for request in requests:
        request_end = request.end_date or request.start_date
        overlap_start = max(entitlement.usage_start, request.start_date)
        overlap_end = min(period_end, request_end)
        if overlap_end < overlap_start:
            continue
        if overlap_start == request.start_date and overlap_end == request_end:
            days += float(request.requested_days or 0)
            continue
        start_breakdown = (
            request.start_date_breakdown
            if overlap_start == request.start_date else "full_day"
        )
        end_breakdown = (
            request.end_date_breakdown
            if overlap_end == request_end else "full_day"
        )
        requested = calculate_requested_days(
            overlap_start, overlap_end, start_breakdown, end_breakdown
        )
        days += cal_effective_requested_days(
            overlap_start,
            overlap_end,
            request.leave_type_id,
            requested,
            employee=assignment.employee_id,
        )
    return days


@locked_employee_sync
@transaction.atomic
def sync_sick_leave(employee, leave_type, as_of=None):
    if leave_type.auto_leave_policy not in {"outpatient_sick", "hospitalisation"}:
        return None
    from leave.models import AvailableLeave

    assignment = (
        AvailableLeave._base_manager.select_for_update()
        .filter(employee_id=employee, leave_type_id=leave_type)
        .first()
    )
    if assignment is None:
        return None
    entitlement = entitlement_for_assignment(assignment, as_of)
    if entitlement is None:
        return assignment
    remaining = max(
        0, entitlement.earned_days - approved_sick_days(assignment, entitlement, as_of)
    )
    if leave_type.auto_leave_policy == "outpatient_sick":
        hospital_assignment = (
            AvailableLeave._base_manager.select_for_update()
            .filter(
                employee_id=employee,
                leave_type_id__auto_leave_policy="hospitalisation",
            )
            .select_related("leave_type_id")
            .first()
        )
        if hospital_assignment:
            hospital_entitlement = entitlement_for_assignment(
                hospital_assignment, as_of
            )
            if hospital_entitlement:
                remaining = min(
                    remaining,
                    max(
                        0,
                        hospital_entitlement.earned_days
                        - approved_sick_days(
                            hospital_assignment, hospital_entitlement, as_of
                        ),
                    ),
                )
    assignment.available_days = remaining
    assignment.carryforward_days = 0
    assignment.auto_entitlement_days = entitlement.earned_days
    assignment.auto_service_year_start = entitlement.usage_start
    assignment.save()
    return assignment
