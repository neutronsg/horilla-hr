from datetime import date
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from leave.annual_entitlement import calculate_entitlement


class CalendarAnnualExamples(SimpleTestCase):
    def entitlement(self, joined, as_of, days=14):
        return calculate_entitlement(joined, as_of, configured_annual_days=days, period_basis="calendar_year")

    def test_august_joiner_and_subsequent_january(self):
        joined = date(2025, 8, 11)
        self.assertEqual(self.entitlement(joined, date(2025, 12, 31)).earned_days, 5)
        self.assertEqual(self.entitlement(joined, date(2026, 1, 1)).earned_days, 0)
        result = self.entitlement(joined, date(2026, 9, 30))
        self.assertEqual(result.service_year_start, date(2026, 1, 1))
        self.assertEqual(result.completed_months, 9)
        self.assertEqual(result.earned_days, 11)

    def test_late_joiner_does_not_lose_initial_service_across_january(self):
        joined = date(2025, 11, 15)
        self.assertEqual(self.entitlement(joined, date(2026, 2, 13)).earned_days, 0)
        self.assertEqual(self.entitlement(joined, date(2026, 2, 14)).earned_days, 4)

    def test_service_safeguard_at_anniversary_and_statutory_minimum(self):
        joined = date(2025, 8, 11)
        first_year = self.entitlement(joined, date(2025, 12, 31)).earned_days
        current = self.entitlement(joined, date(2026, 8, 10)).earned_days
        self.assertGreaterEqual(first_year + current, 14)
        self.assertEqual(self.entitlement(joined, date(2033, 9, 30), days=7).annual_days, 14)

    def test_allowance_is_read_from_leave_type(self):
        result = self.entitlement(date(2025, 8, 11), date(2026, 9, 30), days=20)
        self.assertEqual(result.earned_days, 15)

    def test_unpaid_days_are_not_restored_by_service_safeguard(self):
        result = calculate_entitlement(date(2025, 1, 1), date(2025, 4, 30), configured_annual_days=14,
            period_basis="calendar_year", unpaid_days_in_service_year=4)
        self.assertEqual(result.earned_days, 4)


class CalendarBalanceTests(TestCase):
    def setUp(self):
        from horilla.testkit import make_company, make_employee
        from leave.models import LeaveType
        self.employee = make_employee(company=make_company("Calendar leave"), email="calendar@test.example")
        work = self.employee.employee_work_info
        work.date_joining = date(2025, 8, 11)
        work.save()
        self.leave_type = LeaveType.objects.create(name="Annual", total_days=14, auto_leave_policy="annual", carryforward_type="carryforward", carryforward_max=5)

    def test_existing_anniversary_balance_is_rebuilt_once(self):
        from leave.models import AvailableLeave
        from leave.annual_policy import sync_annual_leave
        with patch("leave.annual_policy.timezone.localdate", return_value=date(2026, 10, 1)):
            assignment = AvailableLeave.objects.create(employee_id=self.employee, leave_type_id=self.leave_type)
        AvailableLeave._base_manager.filter(pk=assignment.pk).update(available_days=1, carryforward_days=5, auto_entitlement_days=1, auto_service_year_start=date(2026, 8, 11), auto_period_basis="")
        result = sync_annual_leave(self.employee, self.leave_type, date(2026, 10, 1))
        self.assertEqual(result.available_days, 11)
        self.assertEqual(result.carryforward_days, 5)
        self.assertEqual(sync_annual_leave(self.employee, self.leave_type, date(2026, 10, 1)).available_days, 11)

    def test_first_partial_year_rolls_on_january_not_august(self):
        from leave.models import AvailableLeave
        from leave.annual_policy import sync_annual_leave
        with patch("leave.annual_policy.timezone.localdate", return_value=date(2025, 12, 31)):
            AvailableLeave.objects.create(employee_id=self.employee, leave_type_id=self.leave_type)
        result = sync_annual_leave(self.employee, self.leave_type, date(2026, 9, 30))
        self.assertEqual(result.available_days, 11)
        self.assertEqual(result.carryforward_days, 5)
        self.assertEqual(result.expired_date, date(2027, 1, 1))

    def test_conversion_preserves_already_approved_future_leave(self):
        from leave.models import AvailableLeave, LeaveRequest
        from leave.annual_policy import sync_annual_leave
        with patch("leave.annual_policy.timezone.localdate", return_value=date(2026, 10, 1)):
            assignment = AvailableLeave.objects.create(employee_id=self.employee, leave_type_id=self.leave_type)
        request = LeaveRequest.objects.create(employee_id=self.employee, leave_type_id=self.leave_type,
            start_date=date(2026, 11, 17), end_date=date(2026, 11, 17), status="approved", requested_days=1, description="Future approved leave")
        LeaveRequest.objects.filter(pk=request.pk).update(approved_available_days=1)
        AvailableLeave._base_manager.filter(pk=assignment.pk).update(auto_period_basis="", available_days=0)
        result = sync_annual_leave(self.employee, self.leave_type, date(2026, 10, 1))
        self.assertEqual(result.available_days, 10)
