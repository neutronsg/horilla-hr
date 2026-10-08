"""Keep auto-calculated annual leave balances in step with service time."""

import math
from copy import copy
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


def _update_annual_balance(assignment, as_of=None):
    """Update balance fields in memory, preserving existing booked deductions."""
    if assignment.leave_type_id.auto_leave_policy != "annual":
        return None
    entitlement = entitlement_for_assignment(assignment, as_of)
    if entitlement is None:
        return None
    as_of = as_of or timezone.localdate()
    if assignment.auto_period_basis != "calendar_year" or assignment.auto_service_year_start is None:
        assignment.available_days = entitlement.earned_days - _approved_current_year_days(
            assignment, entitlement.service_year_start, as_of
        )
    else:
        # A rollover is exactly a change of calendar year. Close each year
        # crossed since the last sync, never a year after ``as_of``. Earned
        # days for the closing year use the current joining date, so a
        # corrected date cannot carry forward service that never happened.
        rolled_over = False
        last_year = min(entitlement.service_year_start.year, as_of.year)
        while assignment.auto_service_year_start.year < last_year:
            year_end = date(assignment.auto_service_year_start.year, 12, 31)
            prior_year = entitlement_for_assignment(assignment, year_end)
            if prior_year:
                assignment.available_days += (
                    prior_year.earned_days - assignment.auto_entitlement_days
                )
            # Keep approved leave charged to the balances used at approval;
            # its dates do not move those deductions into a different year.
            # If an entitlement correction makes the closing balance negative,
            # retain that deficit rather than refunding already booked leave.
            deficit = min(assignment.available_days, 0)
            _carryforward(assignment)
            assignment.available_days = deficit
            assignment.auto_entitlement_days = 0
            assignment.auto_service_year_start = year_end + date.resolution
            rolled_over = True
        # Credit only the change in earned days. This covers monthly accrual
        # and joining-date corrections alike, while keeping approved
        # deductions and manual HR adjustments already in the balance.
        assignment.available_days += (
            entitlement.earned_days - assignment.auto_entitlement_days
        )
        if rolled_over and assignment.carryforward_days:
            assignment.expired_date = date(entitlement.service_year_start.year + 1, 1, 1)
    assignment.auto_entitlement_days = entitlement.earned_days
    assignment.auto_service_year_start = entitlement.service_year_start
    assignment.auto_period_basis = "calendar_year"
    return assignment


def calculate_annual_balance(assignment, as_of=None):
    """Preview a copy, including save-time normalization, without saving."""
    updated = _update_annual_balance(copy(assignment), as_of)
    if updated is not None:
        updated.pre_save_processing()
    return updated


@transaction.atomic
def sync_annual_leave(employee, leave_type, as_of=None):
    """Credit entitlement differences while keeping booked deductions."""
    from leave.models import AvailableLeave

    if leave_type.auto_leave_policy != "annual":
        return None
    # The company-aware manager adds DISTINCT, which PostgreSQL cannot combine
    # with FOR UPDATE. Lock the unique assignment through the base manager.
    assignment = (
        AvailableLeave._base_manager.select_for_update()
        .filter(employee_id=employee, leave_type_id=leave_type)
        .first()
    )
    if assignment is None:
        return None
    updated = _update_annual_balance(assignment, as_of)
    if updated is None:
        return assignment
    assignment.save()
    return assignment
