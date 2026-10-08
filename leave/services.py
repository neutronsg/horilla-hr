"""
leave/services.py

Centralised business-logic helpers for the leave app.
Condition evaluation follows the same pattern as payroll allowance eligibility checks.
"""

import logging

from django.db import transaction
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)


def evaluate_leave_type_conditions(leave_type, employee):
    """
    Evaluate all conditions configured on a LeaveType against an employee.

    Returns a (is_eligible, error_message) tuple.  When all conditions pass,
    returns (True, None).  On the first failing condition it returns
    (False, <translated error string>).

    Usage::

        is_eligible, msg = evaluate_leave_type_conditions(leave_type, employee)
        if not is_eligible:
            raise ValidationError(msg)
    """
    from leave.models import AvailableLeave

    for condition in leave_type.conditions.all():
        ctype = condition.condition_type

        if ctype == "gender":
            emp_gender = (getattr(employee, "gender", None) or "").lower()
            required_gender = (condition.value or "").lower()
            if emp_gender and required_gender and emp_gender != required_gender:
                return False, _(
                    "This leave type is restricted to {gender} employees only."
                ).format(gender=condition.value)

        elif ctype == "once_per_employment":
            already_assigned = AvailableLeave.objects.filter(
                employee_id=employee,
                leave_type_id=leave_type,
            ).exists()
            if already_assigned:
                return False, _(
                    "'{leave_type}' can only be assigned once per employment and has already been assigned to this employee."
                ).format(leave_type=leave_type.name)

        elif ctype == "marital_status":
            emp_status = (getattr(employee, "marital_status", None) or "").lower()
            required_status = (condition.value or "").lower()
            if emp_status and required_status and emp_status != required_status:
                return False, _(
                    "This leave type is restricted to employees with marital status: {status}."
                ).format(status=condition.value)

        elif ctype == "nationality":
            emp_country = (getattr(employee, "country", None) or "").lower()
            required_country = (condition.value or "").lower()
            if emp_country and required_country and emp_country != required_country:
                return False, _(
                    "This leave type is restricted to employees with nationality: {nationality}."
                ).format(nationality=condition.value)

        elif ctype == "department":
            dept = None
            work_info = getattr(employee, "employee_work_info", None)
            if work_info:
                dept_obj = getattr(work_info, "department_id", None)
                if dept_obj:
                    dept = str(dept_obj).lower()
            required_dept = (condition.value or "").lower()
            if dept and required_dept and dept != required_dept:
                return False, _(
                    "This leave type is restricted to employees in the {department} department."
                ).format(department=condition.value)

        elif ctype == "employment_type":
            emp_type = None
            work_info = getattr(employee, "employee_work_info", None)
            if work_info:
                emp_type_obj = getattr(work_info, "employee_type_id", None)
                if emp_type_obj:
                    emp_type = str(emp_type_obj).lower()
            required_type = (condition.value or "").lower()
            if emp_type and required_type and emp_type != required_type:
                return False, _(
                    "This leave type is restricted to employees with employment type: {emp_type}."
                ).format(emp_type=condition.value)

        elif ctype == "grade":
            grade = None
            work_info = getattr(employee, "employee_work_info", None)
            if work_info:
                grade_obj = getattr(work_info, "job_position_id", None)
                if grade_obj:
                    grade = str(grade_obj).lower()
            required_grade = (condition.value or "").lower()
            if grade and required_grade and grade != required_grade:
                return False, _(
                    "This leave type is restricted to employees with grade: {grade}."
                ).format(grade=condition.value)

    return True, None


def has_sufficient_leave_balance(available_leave, requested_days) -> bool:
    """
    Gate used by leave_request_approve before deducting balance.

    Returns True when available_days + carryforward_days covers requested_days.
    """
    total = (available_leave.available_days or 0) + (
        available_leave.carryforward_days or 0
    )
    return total >= float(requested_days or 0)


def get_condition_display_choices():
    """
    Returns a dict of {condition_type: suggested value choices} for UI hints.
    """
    return {
        "gender": [("male", _("Male")), ("female", _("Female")), ("other", _("Other"))],
        "marital_status": [
            ("single", _("Single")),
            ("married", _("Married")),
            ("divorced", _("Divorced")),
        ],
        "once_per_employment": [],
        "nationality": [],
        "department": [],
        "employment_type": [],
        "grade": [],
        "service_duration": [],
    }


def sync_auto_leave(employee, as_of=None):
    """
    Recalculate every automatic (annual and sick) leave balance of one employee.
    """
    from leave.annual_policy import sync_annual_leave
    from leave.models import AvailableLeave
    from leave.sick_policy import sync_sick_leave

    assignments = (
        AvailableLeave._base_manager.filter(employee_id=employee)
        .exclude(leave_type_id__auto_leave_policy="none")
        .select_related("leave_type_id")
    )
    for assignment in assignments:
        leave_type = assignment.leave_type_id
        if leave_type.auto_leave_policy == "annual":
            sync_annual_leave(employee, leave_type, as_of)
        else:
            sync_sick_leave(employee, leave_type, as_of)


def schedule_auto_leave_sync(employees):
    """
    Recalculate automatic leave after the current transaction commits.

    Used when a joining or contract end date changes. Failures are logged
    rather than raised so that saving employee details is never blocked; the
    periodic leave job retries the calculation.
    """
    employees = list(employees)
    if not employees:
        return

    def _sync():
        for employee in employees:
            try:
                sync_auto_leave(employee)
            except Exception:
                logger.exception(
                    "Automatic leave sync failed for employee %s",
                    getattr(employee, "pk", employee),
                )

    transaction.on_commit(_sync)
