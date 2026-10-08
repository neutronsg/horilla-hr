"""HR may record paid leave inside the first three months of service."""

from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase

from horilla import horilla_middlewares

TODAY = date(2026, 10, 8)


class ServiceGateOverrideTests(TestCase):
    def setUp(self):
        from horilla.testkit import make_company, make_employee
        from leave.models import AvailableLeave, LeaveType

        company = make_company("Service Gate Co")
        self.employee = make_employee(company=company, email="new@test.horilla")
        self.employee.employee_work_info.date_joining = date(2026, 5, 1)
        self.employee.employee_work_info.save()
        self.hr = make_employee(company=company, email="hr@test.horilla")
        self.manager = make_employee(company=company, email="manager@test.horilla")
        self.leave_type = LeaveType.objects.create(
            name="Annual Leave", total_days=14, auto_leave_policy="annual"
        )
        with patch("leave.annual_policy.timezone.localdate", return_value=TODAY):
            AvailableLeave.objects.create(
                employee_id=self.employee, leave_type_id=self.leave_type
            )
        self.addCleanup(setattr, horilla_middlewares._thread_locals, "request", None)

    def grant_add_permission(self, employee, codename="add_leaverequest"):
        employee.employee_user_id.user_permissions.add(
            Permission.objects.get(content_type__app_label="leave", codename=codename)
        )

    def clean_as(self, employee):
        from horilla_auth.models import HorillaUser
        from leave.models import LeaveRequest

        # Reload the user so Django's permission cache sees granted permissions.
        user = HorillaUser.objects.get(pk=employee.employee_user_id.pk)
        http_request = RequestFactory().get("/")
        http_request.user = user
        horilla_middlewares._thread_locals.request = http_request
        request = LeaveRequest(
            employee_id=self.employee,
            leave_type_id=self.leave_type,
            start_date=date(2026, 7, 17),
            end_date=date(2026, 7, 17),
            description="AL",
        )
        with patch("leave.models.timezone.localdate", return_value=TODAY), patch(
            "leave.annual_policy.timezone.localdate", return_value=TODAY
        ):
            request.clean()

    def test_hr_can_record_leave_before_three_months_of_service(self):
        self.grant_add_permission(self.hr)
        self.clean_as(self.hr)

    def test_hr_editing_with_change_permission_can_override(self):
        self.grant_add_permission(self.hr, "change_leaverequest")
        self.clean_as(self.hr)

    def test_employee_applying_for_themselves_is_still_blocked(self):
        with self.assertRaisesMessage(ValidationError, "three months"):
            self.clean_as(self.employee)

    def test_add_permission_does_not_override_own_leave(self):
        self.grant_add_permission(self.employee)
        with self.assertRaisesMessage(ValidationError, "three months"):
            self.clean_as(self.employee)

    def test_manager_without_add_permission_is_still_blocked(self):
        with self.assertRaisesMessage(ValidationError, "three months"):
            self.clean_as(self.manager)

    def test_override_still_requires_leave_balance(self):
        from leave.models import AvailableLeave

        AvailableLeave._base_manager.filter(employee_id=self.employee).update(
            available_days=0, auto_entitlement_days=6, auto_period_basis="calendar_year",
            auto_service_year_start=date(2026, 5, 1),
        )
        self.grant_add_permission(self.hr)
        with self.assertRaisesMessage(ValidationError, "sufficient leave balance"):
            self.clean_as(self.hr)
