"""Reuse existing HR/Admin membership and permissions in a concrete company."""

from base.auth_backends import (
    get_allowed_company_ids,
    get_effective_permission_codenames,
    get_user_groups_for_company,
)


def can_manage_claim_reminders(user, company_id):
    if not user.is_authenticated or not user.is_active or not company_id:
        return False
    if user.is_superuser:
        return True
    return (
        company_id in get_allowed_company_ids(user)
        and get_user_groups_for_company(user, company_id)
        .filter(name__in=("HR Manager", "Admin"))
        .exists()
        and "change_reimbursement"
        in get_effective_permission_codenames(user, company_id)
    )


def can_email_payslip(user, payslip):
    company_id = payslip.employee_id.employee_work_info.company_id_id
    if not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    permissions = get_effective_permission_codenames(user, company_id)
    return company_id in get_allowed_company_ids(user) and {
        "add_payslip",
        "view_payslip",
    }.issubset(permissions)
