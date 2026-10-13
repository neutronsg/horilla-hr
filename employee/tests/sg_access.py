"""Existing HR role assignments for Singapore employee access tests."""
from django.contrib.auth.models import Group, Permission

from base.models import CompanyGroupAssignment


def grant_hr_employee_access(employee, *, view_only=False, role="HR Manager", company=None):
    user = employee.employee_user_id
    company = company or employee.employee_work_info.company_id
    group, _ = Group.objects.get_or_create(name=role)
    codenames = ["view_employee"] if view_only else ["view_employee", "change_employee"]
    group.permissions.set(Permission.objects.filter(
        content_type__app_label="employee", codename__in=codenames,
    ))
    CompanyGroupAssignment.objects.get_or_create(user=user, group=group, company=company)
    user.groups.add(group)  # Also exercise the legacy global role configuration.
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)
