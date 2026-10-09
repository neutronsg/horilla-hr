"""Company absence projection, separate from private leave-management access."""

import calendar
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from base.models import CompanyLeaves, Holidays
from leave.models import AvailableLeave, LeaveRequest
from leave.services import has_company_hr_permission


def _company_id(user):
    # An ESS calendar always belongs to the employee's company. Neither an
    # "all companies" session nor a supplied company/employee ID widens it.
    employee = getattr(user, "employee_get", None)
    work = getattr(employee, "employee_work_info", None)
    return getattr(work, "company_id_id", None)


def _today():
    return timezone.localdate(timezone=ZoneInfo("Asia/Singapore"))


def _visible_requests(company_id):
    return LeaveRequest._base_manager.filter(
        employee_id__employee_work_info__company_id_id=company_id,
        is_active=True,
    ).filter(
        Q(status="approved")
        | Q(status="cancelled", approved_available_days__gt=0)
        | Q(status="cancelled", approved_carryforward_days__gt=0)
    )


def _days(start, end):
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _off_days(company_id, days):
    rules = list(CompanyLeaves._base_manager.filter(
        Q(company_id=company_id) | Q(company_id__isnull=True)
    ).distinct())
    result = set()
    for day in days:
        weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(day.year, day.month)
        week = next(i for i, row in enumerate(weeks) if day.day in row)
        for rule in rules:
            if rule.based_on_week_day == str(day.weekday()) and (
                rule.based_on_week in (None, "", str(week))
            ):
                result.add(day)
                break
    return result


def _holiday_dates(holiday, days):
    end = holiday.end_date or holiday.start_date
    if not holiday.recurring:
        return {day for day in days if holiday.start_date <= day <= end}
    duration = (end - holiday.start_date).days
    result = set()
    for year in {day.year for day in days} | {days[0].year - 1}:
        try:
            start = holiday.start_date.replace(year=year)
        except ValueError:  # A recurring February 29 has no occurrence this year.
            continue
        result.update(day for day in days if start <= day <= start + timedelta(days=duration))
    return result


@login_required
@require_GET
@never_cache
def company_leave_calendar(request):
    company_id = _company_id(request.user)
    if company_id is None:
        return JsonResponse({"error": "No employee company is linked to this account."}, status=403)
    today = _today()
    try:
        start = date.fromisoformat(request.GET.get("start", today.replace(day=1).isoformat()))
        end = date.fromisoformat(request.GET.get("end", today.replace(
            day=calendar.monthrange(today.year, today.month)[1]
        ).isoformat()))
        if not 0 <= (end - start).days <= 61:
            raise ValueError
    except (ValueError, TypeError):
        return JsonResponse({"error": "Select a valid date range of at most 62 days."}, status=400)

    days = _days(start, end)
    off_days = _off_days(company_id, days)
    holidays = list(Holidays._base_manager.filter(
        Q(company_id_id=company_id) | Q(company_id__isnull=True), is_active=True,
    ).prefetch_related("employees"))
    holiday_days = {h.pk: _holiday_dates(h, days) for h in holidays}
    requests = _visible_requests(company_id).filter(
        start_date__lte=end, end_date__gte=start
    ).select_related(
        "employee_id", "employee_id__employee_work_info__department_id", "leave_type_id"
    ).order_by("start_date", "employee_id__employee_first_name", "pk")
    events = []
    departments = {}
    search = request.GET.get("q", "").strip().casefold()[:100]
    department_filter = request.GET.get("department", "")
    for item in requests:
        employee = item.employee_id
        work = employee.employee_work_info
        department = work.department_id
        department_id = str(department.pk) if department else ""
        if department:
            departments[department_id] = str(department)
        name = employee.get_full_name()
        if search and search not in name.casefold():
            continue
        if department_filter and department_id != department_filter:
            continue
        employee_holidays = set()
        for holiday in holidays:
            if not holiday.is_specific or employee.pk in {e.pk for e in holiday.employees.all()}:
                employee_holidays.update(holiday_days[holiday.pk])
        occurrences = []
        for day in _days(max(start, item.start_date), min(end, item.end_date)):
            if item.leave_type_id.exclude_company_leave == "yes" and day in off_days:
                continue
            if item.leave_type_id.exclude_holiday == "yes" and day in employee_holidays:
                continue
            part = "full_day"
            if day == item.start_date and item.start_date_breakdown != "full_day":
                part = item.start_date_breakdown
            elif day == item.end_date and item.end_date_breakdown != "full_day":
                part = item.end_date_breakdown
            occurrences.append({"date": day.isoformat(), "part": part})
        if occurrences:
            events.append({
                "id": item.pk, "name": name, "department": str(department) if department else "",
                "department_id": department_id, "start": item.start_date.isoformat(),
                "end": item.end_date.isoformat(), "days": occurrences,
            })
    response = JsonResponse({
        "today": today.isoformat(), "start": start.isoformat(), "end": end.isoformat(),
        "events": events,
        "departments": [{"id": pk, "name": name} for pk, name in sorted(departments.items(), key=lambda row: row[1])],
        "off_days": sorted(day.isoformat() for day in off_days),
        "holidays": [{"date": day.isoformat(), "name": h.name} for h in holidays
                     if not h.is_specific for day in sorted(holiday_days[h.pk])],
        "can_view_details": has_company_hr_permission(request.user, company_id, "view_leaverequest"),
    })
    return response


@login_required
@require_GET
@never_cache
def company_leave_detail(request, pk):
    company_id = _company_id(request.user)
    if company_id is None or not has_company_hr_permission(
        request.user, company_id, "view_leaverequest"
    ):
        return JsonResponse({"error": "HR/Admin leave-view access is required."}, status=403)
    item = get_object_or_404(_visible_requests(company_id).select_related(
        "employee_id", "leave_type_id", "created_by"
    ), pk=pk)
    balance = AvailableLeave._base_manager.filter(
        employee_id=item.employee_id, leave_type_id=item.leave_type_id
    ).first()
    steps = item.leaverequestconditionapproval_set.select_related("manager_id").order_by("sequence", "pk")
    comments = item.leaverequestcomment_set.select_related("employee_id").order_by("created_at", "pk")
    history = item.history.select_related("history_user").order_by("history_date", "history_id")
    return JsonResponse({
        "name": item.employee_id.get_full_name(), "leave_type": item.leave_type_id.name,
        "description": item.description, "status": item.status,
        "requested_days": item.requested_days,
        "attachment": item.attachment.url if item.attachment else None,
        "available_days": balance.available_days if balance else None,
        "carryforward_days": balance.carryforward_days if balance else None,
        "created_by": item.created_by.get_full_name() if item.created_by else None,
        "approvals": [{"name": step.manager_id.get_full_name(), "sequence": step.sequence,
                       "approved": step.is_approved, "rejected": step.is_rejected} for step in steps],
        "comments": [{"name": entry.employee_id.get_full_name(), "text": entry.comment,
                      "at": entry.created_at.isoformat() if entry.created_at else None} for entry in comments],
        "history": [{"status": entry.status, "at": entry.history_date.isoformat(),
                     "actor": str(entry.history_user) if entry.history_user else None,
                     "deducted": entry.approved_available_days + entry.approved_carryforward_days}
                    for entry in history],
    })
