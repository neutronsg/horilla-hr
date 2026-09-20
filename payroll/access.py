"""Employee payslips are released once payroll confirms them."""

EMPLOYEE_VISIBLE_STATUSES = ("confirmed", "paid")


def can_view_payslip(user, payslip):
    """Keep HR preview access; employees may only access their own confirmed or paid slips."""
    return user.has_perm("payroll.view_payslip") or (
        payslip.status in EMPLOYEE_VISIBLE_STATUSES
        and payslip.employee_id.employee_user_id == user
    )


def visible_payslips(user, queryset):
    """Apply release and ownership rules without losing existing query filters."""
    if user.has_perm("payroll.view_payslip"):
        return queryset
    return queryset.filter(
        employee_id__employee_user_id=user, status__in=EMPLOYEE_VISIBLE_STATUSES
    )
