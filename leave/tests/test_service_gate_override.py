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

        group, _ = Group.objects.get_or_create(name=name)
        group.permissions.set(permissions)
        CompanyGroupAssignment.objects.create(
            user=employee.employee_user_id, company=company, group=group
        )

    def hr_permissions(self):
        return Permission.objects.filter(
            codename__in=("add_leaverequest", "change_employeeworkinformation")
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

    def test_hr_with_existing_permissions_can_record_early_leave(self):
        self.assign_role(self.hr, self.company, self.hr_permissions(), "HR Manager")
        self.clean_as(self.hr)

    def test_default_hr_manager_can_override_without_an_extra_permission(self):
        from base.signals import _DEFAULT_HRMS_GROUPS, _resolve_group_permissions

        permissions = _resolve_group_permissions(_DEFAULT_HRMS_GROUPS["HR Manager"])
        self.assign_role(self.hr, self.company, permissions, "HR Manager")
        self.clean_as(self.hr)

    def test_company_admin_can_override_without_being_superuser(self):
        from base.signals import _DEFAULT_HRMS_GROUPS, _resolve_group_permissions

        permissions = _resolve_group_permissions(_DEFAULT_HRMS_GROUPS["Admin"])
        self.assign_role(self.hr, self.company, permissions, "Admin")
        self.assertFalse(self.hr.employee_user_id.is_superuser)
        self.clean_as(self.hr)

    def test_non_hr_role_with_both_permissions_cannot_override(self):
        self.assign_role(self.hr, self.company, self.hr_permissions(), "Custom role")
        with self.assertRaisesMessage(ValidationError, "three months"):
            self.clean_as(self.hr)

    def test_combining_leave_and_payroll_or_recruiter_roles_cannot_override(self):
        from base.signals import _DEFAULT_HRMS_GROUPS, _resolve_group_permissions
        from base.models import CompanyGroupAssignment

        for other_role in ("Payroll Manager", "Recruiter"):
            with self.subTest(other_role=other_role):
                CompanyGroupAssignment.objects.filter(user=self.hr.employee_user_id).delete()
                for role in ("Leave Manager", other_role):
                    self.assign_role(
                        self.hr, self.company,
                        _resolve_group_permissions(_DEFAULT_HRMS_GROUPS[role]), role,
                    )
                with self.assertRaisesMessage(ValidationError, "three months"):
                    self.clean_as(self.hr)

    def test_leave_manager_role_cannot_override(self):
        from base.signals import _DEFAULT_HRMS_GROUPS, _resolve_group_permissions

        leave_manager = _resolve_group_permissions(_DEFAULT_HRMS_GROUPS["Leave Manager"])
        self.assertTrue(leave_manager.filter(codename="add_leaverequest").exists())
        self.assign_role(self.hr, self.company, leave_manager, "Scoped Leave Manager")
        with self.assertRaisesMessage(ValidationError, "three months"):
            self.clean_as(self.hr)

    def test_payroll_manager_role_cannot_override(self):
        from base.signals import _DEFAULT_HRMS_GROUPS, _resolve_group_permissions

        permissions = _resolve_group_permissions(_DEFAULT_HRMS_GROUPS["Payroll Manager"])
        self.assign_role(self.hr, self.company, permissions, "Scoped Payroll Manager")
        with self.assertRaisesMessage(ValidationError, "three months"):
            self.clean_as(self.hr)

    def test_work_information_permission_alone_cannot_override(self):
        self.assign_role(
            self.hr, self.company,
            self.hr_permissions().filter(codename="change_employeeworkinformation"),
            "Work information editor",
        )
        with self.assertRaisesMessage(ValidationError, "three months"):
            self.clean_as(self.hr)

    def test_override_granted_for_another_company_does_not_apply(self):
        self.assign_role(
            self.hr, self.other_company, self.hr_permissions(), "HR Manager"
        )
        with self.assertRaisesMessage(ValidationError, "three months"):
            self.clean_as(self.hr)

    def test_company_admin_in_another_company_cannot_override(self):
        self.assign_role(self.hr, self.other_company, self.hr_permissions(), "Admin")
        with self.assertRaisesMessage(ValidationError, "three months"):
            self.clean_as(self.hr)

    def test_employee_without_company_does_not_use_union_of_hr_roles(self):
        from employee.models import EmployeeWorkInformation

        self.assign_role(self.hr, self.company, self.hr_permissions(), "HR Manager")
        EmployeeWorkInformation._base_manager.filter(employee_id=self.employee).update(
            company_id=None,
        )
        self.employee.employee_work_info.refresh_from_db()
        with self.assertRaisesMessage(ValidationError, "three months"):
            self.clean_as(self.hr)

    def test_permissions_in_different_companies_cannot_be_combined(self):
        self.assign_role(
            self.hr, self.company,
            self.hr_permissions().filter(codename="add_leaverequest"), "Leave creator",
        )
        self.assign_role(
            self.hr, self.other_company,
            self.hr_permissions().filter(codename="change_employeeworkinformation"),
            "Other company editor",
        )
        with self.assertRaisesMessage(ValidationError, "three months"):
            self.clean_as(self.hr)

    def test_employee_applying_for_themselves_is_still_blocked(self):
        with self.assertRaisesMessage(ValidationError, "three months"):
            self.clean_as(self.employee)

    def test_hr_permissions_do_not_cover_own_leave(self):
        self.assign_role(
            self.employee, self.company, self.hr_permissions(), "HR Manager"
        )
        with self.assertRaisesMessage(ValidationError, "three months"):
            self.clean_as(self.employee)

    def test_superuser_can_record_another_employees_early_leave(self):
        user = self.hr.employee_user_id
        user.is_superuser = True
        user.save()
        self.clean_as(self.hr)

    def test_superuser_own_leave_is_still_blocked(self):
        user = self.employee.employee_user_id
        user.is_superuser = True
        user.save()
        with self.assertRaisesMessage(ValidationError, "three months"):
            self.clean_as(self.employee)

    def test_global_hr_group_works_when_company_scoping_is_disabled(self):
        with override_settings(COMPANY_SCOPED_PERMISSIONS=False):
            group, _ = Group.objects.get_or_create(name="HR Manager")
            group.permissions.set(self.hr_permissions())
            self.hr.employee_user_id.groups.add(group)
            self.clean_as(self.hr)

    def test_override_still_requires_leave_balance(self):
        from leave.models import AvailableLeave

        AvailableLeave._base_manager.filter(employee_id=self.employee).update(
            available_days=0, auto_entitlement_days=6, auto_period_basis="calendar_year",
            auto_service_year_start=date(2026, 5, 1),
        )
        self.assign_role(self.hr, self.company, self.hr_permissions(), "HR Manager")
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
        self.assign_role(self.hr, self.company, self.hr_permissions(), "HR Manager")
        with self.assertRaisesMessage(ValidationError, "before the employee's joining date"):
            self.clean_as(self.hr)
