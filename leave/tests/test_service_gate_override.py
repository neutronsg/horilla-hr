"""HR may record paid leave inside the first three months of service."""

from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase, override_settings

from horilla import horilla_middlewares

TODAY = date(2026, 10, 8)


@override_settings(COMPANY_SCOPED_PERMISSIONS=True)
class ServiceGateOverrideTests(TestCase):
    def setUp(self):
        from horilla.testkit import make_company, make_employee
        from leave.models import AvailableLeave, LeaveType

        self.company = make_company("Service Gate Co")
        self.other_company = make_company("Other Gate Co")
        self.employee = make_employee(company=self.company, email="new@test.horilla")
        self.employee.employee_work_info.date_joining = date(2026, 5, 1)
        self.employee.employee_work_info.save()
        self.hr = make_employee(company=self.company, email="hr@test.horilla")
        self.leave_type = LeaveType.objects.create(
            name="Annual Leave", total_days=14, auto_leave_policy="annual"
        )
        with patch("leave.annual_policy.timezone.localdate", return_value=TODAY):
            AvailableLeave.objects.create(
                employee_id=self.employee, leave_type_id=self.leave_type
            )
        self.addCleanup(setattr, horilla_middlewares._thread_locals, "request", None)

    def assign_role(self, employee, company, permissions, name):
        """Grant a role the way production does: per company, not user.groups."""
        from base.models import CompanyGroupAssignment

        group = Group.objects.create(name=name)
        group.permissions.set(permissions)
        CompanyGroupAssignment.objects.create(
            user=employee.employee_user_id, company=company, group=group
        )

    def override_permission(self):
        return Permission.objects.filter(
            content_type__app_label="leave", codename="override_service_gate"
        )

    def clean_as(self, employee, start=date(2026, 7, 17)):
        from horilla_auth.models import HorillaUser
        from leave.models import LeaveRequest

        # Reload the user so no permission cache survives between grants.
        user = HorillaUser.objects.get(pk=employee.employee_user_id.pk)
        http_request = RequestFactory().get("/")
        http_request.user = user
        horilla_middlewares._thread_locals.request = http_request
        request = LeaveRequest(
            employee_id=self.employee,
            leave_type_id=self.leave_type,
            start_date=start,
            end_date=start,
            description="AL",
        )
        with patch("leave.models.timezone.localdate", return_value=TODAY), patch(
            "leave.annual_policy.timezone.localdate", return_value=TODAY
        ):
            request.clean()

    def test_hr_with_override_permission_can_record_early_leave(self):
        self.assign_role(self.hr, self.company, self.override_permission(), "HR override")
        self.clean_as(self.hr)

    def test_leave_manager_role_cannot_override(self):
        from base.signals import _DEFAULT_HRMS_GROUPS, _resolve_group_permissions

        leave_manager = _resolve_group_permissions(_DEFAULT_HRMS_GROUPS["Leave Manager"])
        self.assertTrue(leave_manager.filter(codename="add_leaverequest").exists())
        self.assign_role(self.hr, self.company, leave_manager, "Scoped Leave Manager")
        with self.assertRaisesMessage(ValidationError, "three months"):
            self.clean_as(self.hr)

    def test_default_hr_and_leave_roles_do_not_include_override(self):
        from base.signals import _DEFAULT_HRMS_GROUPS, _resolve_group_permissions

        for name in ("HR Manager", "Leave Manager", "Payroll Manager"):
            permissions = _resolve_group_permissions(_DEFAULT_HRMS_GROUPS[name])
            self.assertFalse(
                permissions.filter(codename="override_service_gate").exists(), name
            )

    def test_override_granted_for_another_company_does_not_apply(self):
        self.assign_role(
            self.hr, self.other_company, self.override_permission(), "Other override"
        )
        with self.assertRaisesMessage(ValidationError, "three months"):
            self.clean_as(self.hr)

    def test_employee_applying_for_themselves_is_still_blocked(self):
        with self.assertRaisesMessage(ValidationError, "three months"):
            self.clean_as(self.employee)

    def test_override_permission_does_not_cover_own_leave(self):
        self.assign_role(
            self.employee, self.company, self.override_permission(), "Self override"
        )
        with self.assertRaisesMessage(ValidationError, "three months"):
            self.clean_as(self.employee)

    def test_override_still_requires_leave_balance(self):
        from leave.models import AvailableLeave

        AvailableLeave._base_manager.filter(employee_id=self.employee).update(
            available_days=0, auto_entitlement_days=6, auto_period_basis="calendar_year",
            auto_service_year_start=date(2026, 5, 1),
        )
        self.assign_role(self.hr, self.company, self.override_permission(), "HR override")
        with self.assertRaisesMessage(ValidationError, "sufficient leave balance"):
            self.clean_as(self.hr)

    def test_override_cannot_record_leave_before_joining_date(self):
        from employee.models import EmployeeWorkInformation
        from leave.models import AvailableLeave

        EmployeeWorkInformation.objects.filter(employee_id=self.employee).update(
            date_joining=date(2026, 8, 1)
        )
        AvailableLeave._base_manager.filter(employee_id=self.employee).update(
            available_days=5, auto_entitlement_days=0, auto_period_basis="calendar_year",
            auto_service_year_start=date(2026, 8, 1),
        )
        self.employee.employee_work_info.refresh_from_db()
        self.assign_role(self.hr, self.company, self.override_permission(), "HR override")
        with self.assertRaisesMessage(ValidationError, "before the employee's joining date"):
            self.clean_as(self.hr)
