"""Working-day counts for MOM incomplete-month salary calculations."""

import calendar
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from base.methods import get_company_leave_dates
from base.models import EmployeeShiftSchedule


def employment_period(employee, contract, start, end):
    work = getattr(employee, "employee_work_info", None)
    starts = [start, contract.contract_start_date]
    ends = [end]
    if work and work.date_joining:
        starts.append(work.date_joining)
    for last in (contract.contract_end_date, getattr(work, "contract_end_date", None)):
        if last:
            ends.append(last)
    return max(starts), min(ends)


def working_day_weights(employee, contract, start, end, require_schedule=True):
    """Rest days are excluded; public holidays retain their scheduled weight."""
    work = getattr(employee, "employee_work_info", None)
    shift = contract.shift or getattr(work, "shift_id", None)
    schedule = {}
    if shift:
        for row in EmployeeShiftSchedule.objects.filter(shift_id=shift).select_related("day"):
            hours, minutes = map(int, row.minimum_working_hour.split(":"))
            duration = hours * 60 + minutes
            schedule[row.day.day] = 0 if duration == 0 else (0.5 if duration <= 300 else 1)
    weekly_off = set(get_company_leave_dates(start.year) + get_company_leave_dates(end.year))
    workweek = contract.payroll_workweek
    if not schedule and not workweek and not weekly_off and require_schedule:
        raise ValidationError(_(
            "Set a payroll workweek or shift schedule on %(employee)s's contract "
            "before calculating an incomplete month or unpaid leave."
        ) % {"employee": employee})
    result = {}
    current = start
    while current <= end:
        if workweek:
            weight = float(current.weekday() < {"five_day": 5, "six_day": 6, "seven_day": 7}[workweek])
        elif schedule:
            weight = schedule.get(current.strftime("%A").lower(), 0)
        else:
            weight = float(current not in weekly_off)
        result[current] = weight
        current += timedelta(days=1)
    return result


def month_bounds(day):
    return day.replace(day=1), day.replace(day=calendar.monthrange(day.year, day.month)[1])
