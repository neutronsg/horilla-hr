"""Keep auto-calculated annual leave balances in step with service time."""

import math
from datetime import date

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from employee.models import EmployeeWorkInformation
from leave.annual_entitlement import add_months, calculate_entitlement
from leave.methods import calculate_requested_days


def _work_info(employee):
    return EmployeeWorkInformation.objects.filter(employee_id=employee).first()


def _is_unpaid(leave_type):
    return leave_type.get_payment_percentage() == 0


def _unpaid_days(employee, start, end):
    """Approved unpaid time overlapping one service-year calculation window."""
    from leave.models import LeaveRequest

    requests = (
        LeaveRequest.objects.filter(
            Q(end_date__gte=start) | Q(end_date__isnull=True),
            employee_id=employee,
            status="approved",
            start_date__lte=end,
        )
        .select_related("leave_type_id")
    )
    days = 0.0
    for request in requests:
        if not _is_unpaid(request.leave_type_id):
            continue
        overlap_start = max(start, request.start_date)
        request_end = request.end_date or request.start_date
        overlap_end = min(end, request_end)
        if overlap_end < overlap_start:
            continue
        start_breakdown = (
            request.start_date_breakdown
            if overlap_start == request.start_date
            else "full_day"
        )
        end_breakdown = (
            request.end_date_breakdown
            if overlap_end == request_end
            else "full_day"
        )
        overlap_days = calculate_requested_days(
            overlap_start, overlap_end, start_breakdown, end_breakdown
        )
        if overlap_start == request.start_date and overlap_end == request_end:
            if request.requested_days is not None:
                overlap_days = request.requested_days
        days += overlap_days
    return days


def entitlement_for_assignment(assignment, as_of=None):
    """Return earned entitlement, or None when the joining date is missing."""
    work_info = _work_info(assignment.employee_id)
    joining_date = work_info.date_joining if work_info else None
    if not joining_date:
        return None
    as_of = as_of or timezone.localdate()
    effective_end = (
        min(as_of, work_info.contract_end_date)
        if work_info.contract_end_date
        else as_of
    )
    if effective_end < joining_date:
        return calculate_entitlement(
            joining_date,
            as_of,
            configured_annual_days=float(assignment.leave_type_id.total_days or 0),
            employment_end_date=work_info.contract_end_date,
            period_basis="calendar_year",
        )
    calendar_unpaid = {
        year: _unpaid_days(assignment.employee_id, max(joining_date, date(year, 1, 1)),
                          min(effective_end, date(year, 12, 31)))
        for year in range(joining_date.year, effective_end.year + 1)
    }
    service_unpaid = {}
    for index in range(effective_end.year - joining_date.year + 1):
        start = add_months(joining_date, index * 12)
        if start <= effective_end:
            service_unpaid[index] = _unpaid_days(
                assignment.employee_id, start, min(effective_end, add_months(start, 12) - date.resolution)
            )
    return calculate_entitlement(
        joining_date,
        as_of,
        configured_annual_days=float(assignment.leave_type_id.total_days or 0),
        employment_end_date=work_info.contract_end_date,
        period_basis="calendar_year",
        unpaid_by_calendar_year=calendar_unpaid,
        unpaid_by_service_year=service_unpaid,
    )


def _approved_current_year_days(assignment, start, end):
    """Usage to subtract when an existing manual assignment is first opted in."""
    from leave.models import LeaveRequest

    requests = LeaveRequest.objects.filter(
        employee_id=assignment.employee_id,
        leave_type_id=assignment.leave_type_id,
        status="approved",
        start_date__gte=start,
        start_date__lte=date(start.year, 12, 31),
    )
    return sum(float(request.approved_available_days or 0) for request in requests)


def _carryforward(assignment):
    leave_type = assignment.leave_type_id
    if leave_type.carryforward_type == "no carryforward":
        assignment.carryforward_days = 0
        assignment.expired_date = None
        return
    cap = leave_type.carryforward_max
    assignment.carryforward_days = min(
        max(assignment.available_days, 0),
        cap if cap is not None else math.inf,
    )


@transaction.atomic
def sync_annual_leave(employee, leave_type, as_of=None):
    """Credit completed-month entitlement without repeating previous credits.

    Approved leave continues to deduct from the usual Horilla balance fields.
    We store the last credited entitlement and apply only the difference.
    """
    from leave.models import AvailableLeave

    if leave_type.auto_leave_policy != "annual":
        return None
    # The company-aware default manager adds DISTINCT to its queryset. PostgreSQL
    # cannot combine that with FOR UPDATE, so lock the uniquely identified
    # assignment through the unfiltered base manager instead.
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
    as_of = as_of or timezone.localdate()
    if assignment.auto_period_basis != "calendar_year" or assignment.auto_service_year_start is None:
        assignment.available_days = entitlement.earned_days - _approved_current_year_days(
            assignment, entitlement.service_year_start, as_of
        )
    elif assignment.auto_service_year_start != entitlement.service_year_start:
        if assignment.auto_service_year_start > entitlement.service_year_start:
            # The joining date was corrected. Rebuild the current year from
            # approved usage instead of treating the correction as a rollover.
            assignment.available_days = entitlement.earned_days - _approved_current_year_days(
                assignment, entitlement.service_year_start, as_of
            )
        else:
            while assignment.auto_service_year_start < entitlement.service_year_start:
                next_year_start = date(assignment.auto_service_year_start.year + 1, 1, 1)
                prior_year = entitlement_for_assignment(
                    assignment, next_year_start - date.resolution
                )
                if prior_year:
                    assignment.available_days += (
                        prior_year.earned_days - assignment.auto_entitlement_days
                    )
                _carryforward(assignment)
                assignment.available_days = 0
                assignment.auto_entitlement_days = 0
                assignment.auto_service_year_start = next_year_start
            assignment.available_days = entitlement.earned_days
            if assignment.carryforward_days:
                assignment.expired_date = date(entitlement.service_year_start.year + 1, 1, 1)
    else:
        assignment.available_days += (
            entitlement.earned_days - assignment.auto_entitlement_days
        )
    assignment.auto_entitlement_days = entitlement.earned_days
    assignment.auto_service_year_start = entitlement.service_year_start
    assignment.auto_period_basis = "calendar_year"
    assignment.save()
    return assignment
