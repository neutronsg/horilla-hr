"""Reporting-manager decisions and company HR observers, using existing roles."""

from django.db import transaction
from django.urls import reverse


def company_id_for(item):
    work = getattr(item.employee_id, "employee_work_info", None)
    return getattr(work, "company_id_id", None)


def in_company(user, company_id):
    from base.auth_backends import get_allowed_company_ids

    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and company_id
        and (user.is_superuser or company_id in get_allowed_company_ids(user))
    )


def reporting_manager(item):
    work = getattr(item.employee_id, "employee_work_info", None)
    manager = getattr(work, "reporting_manager_id", None)
    if (
        manager
        and manager.pk != item.employee_id_id
        and manager.is_active
        and manager.employee_user_id
        and manager.employee_user_id.is_active
    ):
        return manager
    return None


def can_review_leave(user, item):
    if not in_company(user, company_id_for(item)):
        return False
    actor = getattr(user, "employee_get", None)
    if not actor or not actor.is_active or actor.pk == item.employee_id_id:
        return False
    from leave.models import LeaveRequestConditionApproval
    from leave.services import next_leave_approval

    if (
        item.status != "cancelled"
        and LeaveRequestConditionApproval._base_manager.filter(
            leave_request_id=item
        ).exists()
    ):
        step = next_leave_approval(item)
        return bool(step and not step.is_rejected and step.manager_id_id == actor.pk)
    manager = reporting_manager(item)
    return bool(manager and manager.pk == actor.pk)


def can_decide_leave(user, item):
    return item.status == "requested" and can_review_leave(user, item)


def can_admin_intervene(user, item):
    if item.status != "requested" or not in_company(user, company_id_for(item)):
        return False
    if user.is_superuser:
        return True
    from base.auth_backends import (
        get_user_groups_for_company,
        get_effective_permission_codenames,
    )

    company_id = company_id_for(item)
    return get_user_groups_for_company(user, company_id).filter(
        name="Admin"
    ).exists() and "change_leaverequest" in get_effective_permission_codenames(
        user, company_id
    )


def is_intervention(request, item):
    # Set only by the dedicated, validated server-side intervention endpoint.
    return bool(
        getattr(request, "leave_intervention_reason", "").strip()
        and getattr(request, "leave_intervention_id", None) == item.pk
    )


def decision_allowed(request, item):
    return can_decide_leave(request.user, item) or is_intervention(request, item)


def hr_observers(item):
    from base.models import CompanyGroupAssignment
    from base.auth_backends import get_effective_permission_codenames
    from employee.models import Employee

    company_id = company_id_for(item)
    ids = CompanyGroupAssignment._base_manager.filter(
        company_id=company_id, group__name="HR Manager"
    ).values_list("user_id", flat=True)
    people = (
        Employee._base_manager.filter(
            employee_user_id__in=ids, is_active=True, employee_user_id__is_active=True
        )
        .select_related("employee_user_id", "employee_work_info")
        .distinct()
    )
    return [
        person
        for person in people
        if "view_leaverequest"
        in get_effective_permission_codenames(person.employee_user_id, company_id)
    ]


def record_decision(request, item, outcome):
    from leave.models import LeaverequestComment

    actor = request.user.employee_get
    reason = (
        getattr(request, "leave_intervention_reason", "")
        if is_intervention(request, item)
        else item.reject_reason if outcome == "rejected" else ""
    ).strip()
    prefix = (
        "Administrator intervention"
        if is_intervention(request, item)
        else "Manager decision"
    )
    LeaverequestComment.objects.create(
        request_id=item,
        employee_id=actor,
        comment=f"{prefix}: {outcome}; by={actor.get_full_name()}; company={company_id_for(item)}"
        + (f"; reason={reason}" if reason else ""),
    )


def schedule_hr_notice(item, event, request):
    if (
        not request
        or not getattr(request, "user", None)
        or not request.user.is_authenticated
    ):
        return
    pk = item.pk

    def send():
        import logging
        from leave.models import LeaveRequest
        from leave.hr_notifications import HRLeaveNoticeThread

        try:
            fresh = LeaveRequest._base_manager.select_related(
                "employee_id__employee_work_info", "leave_type_id"
            ).get(pk=pk)
            HRLeaveNoticeThread(request, fresh, event).start()
        except Exception:
            logging.getLogger(__name__).exception(
                "Could not schedule HR leave notice %s", pk
            )

    transaction.on_commit(send)


def has_manager_work(user):
    from employee.models import EmployeeWorkInformation
    from leave.models import LeaveRequestConditionApproval

    actor = getattr(user, "employee_get", None)
    if not actor:
        return False
    return (
        EmployeeWorkInformation._base_manager.filter(reporting_manager_id=actor)
        .exclude(employee_id=actor)
        .exists()
        or LeaveRequestConditionApproval._base_manager.filter(
            manager_id=actor, is_approved=False
        ).exists()
    )
