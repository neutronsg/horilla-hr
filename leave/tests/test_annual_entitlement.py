"""Examples at MOM's completed-month and whole-day boundaries."""

from datetime import date
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from leave.annual_entitlement import calculate_entitlement, completed_months


class AnnualEntitlementExamples(SimpleTestCase):
    def test_three_month_probation_and_fixed_fourteen_day_allowance(self):
        start = date(2024, 3, 14)
        before = calculate_entitlement(start, date(2024, 6, 12), configured_annual_days=14)
        completed = calculate_entitlement(start, date(2024, 6, 13), configured_annual_days=14)
        eligible = calculate_entitlement(start, date(2024, 6, 14), configured_annual_days=14)
        self.assertEqual(before.earned_days, 0)
        self.assertEqual(completed.completed_months, 3)
        self.assertEqual(completed.earned_days, 4)
        self.assertEqual(eligible.completed_months, 3)
        self.assertEqual(eligible.earned_days, 4)  # 3 / 12 * 14 = 3.5, rounds up

    def test_contract_ending_on_last_day_of_third_month_has_entitlement(self):
        entitlement = calculate_entitlement(
            date(2025, 1, 1),
            date(2025, 3, 31),
            configured_annual_days=14,
            employment_end_date=date(2025, 3, 31),
        )
        self.assertEqual(entitlement.completed_months, 3)
        self.assertEqual(entitlement.earned_days, 4)

    def test_incomplete_month_is_disregarded(self):
        start = date(2024, 3, 14)
        self.assertEqual(completed_months(start, date(2024, 7, 31)), 4)
        entitlement = calculate_entitlement(
            start, date(2024, 7, 31), configured_annual_days=14
        )
        self.assertEqual(entitlement.earned_days, 5)  # 4 / 12 * 14 = 4.67

    def test_mom_four_month_ten_day_example_rounds_down(self):
        entitlement = calculate_entitlement(
            date(2014, 3, 14), date(2014, 7, 31), configured_annual_days=10
        )
        self.assertEqual(entitlement.completed_months, 4)
        self.assertEqual(entitlement.earned_days, 3)  # 4 / 12 * 10 = 3.33

    def test_contract_end_caps_earned_days(self):
        start = date(2025, 1, 1)
        end = date(2025, 6, 30)
        at_three_months = calculate_entitlement(
            start, date(2025, 4, 1), configured_annual_days=14, employment_end_date=end
        )
        after_contract = calculate_entitlement(
            start, date(2025, 8, 1), configured_annual_days=14, employment_end_date=end
        )
        self.assertEqual(at_three_months.earned_days, 4)
        self.assertEqual(after_contract.completed_months, 6)
        self.assertEqual(after_contract.earned_days, 7)

    def test_unpaid_days_reduce_completed_service_months(self):
        start = date(2025, 1, 1)
        entitlement = calculate_entitlement(
            start,
            date(2025, 4, 30),
            configured_annual_days=12,
            unpaid_days_in_service_year=4,
        )
        self.assertEqual(entitlement.completed_months, 3)
        self.assertEqual(entitlement.earned_days, 3)

    def test_mom_minimum_applies_if_leave_type_is_lower(self):
        start = date(2020, 1, 1)
        second_year = calculate_entitlement(
            start, date(2021, 12, 31), configured_annual_days=7
        )
        eighth_year = calculate_entitlement(
            start, date(2027, 12, 31), configured_annual_days=7
        )
        self.assertEqual(second_year.annual_days, 8)
        self.assertEqual(eighth_year.annual_days, 14)

    def test_anniversary_starts_a_new_service_year(self):
        start = date(2024, 3, 14)
        last_day = calculate_entitlement(
            start, date(2025, 3, 13), configured_annual_days=14
        )
        new_year = calculate_entitlement(
            start, date(2025, 3, 14), configured_annual_days=14
        )
        self.assertEqual(last_day.earned_days, 14)
        self.assertEqual(new_year.service_year_start, date(2025, 3, 14))
        self.assertEqual(new_year.earned_days, 0)


class AnnualBalanceIntegrationTests(TestCase):
    def setUp(self):
        from horilla.testkit import make_company, make_employee
        from leave.models import LeaveType

        company = make_company("Annual Leave Co")
        self.employee = make_employee(company=company, email="annual@test.horilla")
        self.employee.employee_work_info.date_joining = date(2025, 1, 1)
        self.employee.employee_work_info.save()
        self.leave_type = LeaveType.objects.create(
            name="Annual Leave",
            total_days=14,
            auto_annual_leave=True,
            carryforward_type="carryforward",
            carryforward_max=14,
        )

    def test_assignment_credits_completed_months_only_once(self):
        from leave.annual_policy import sync_annual_leave
        from leave.models import AvailableLeave

        with patch("leave.annual_policy.timezone.localdate", return_value=date(2025, 3, 31)):
            assignment = AvailableLeave.objects.create(
                employee_id=self.employee,
                leave_type_id=self.leave_type,
                available_days=14,
            )
        self.assertEqual(assignment.available_days, 4)

        assignment = sync_annual_leave(
            self.employee, self.leave_type, date(2025, 4, 1)
        )
        self.assertEqual(assignment.available_days, 4)
        assignment.available_days -= 2  # Already approved annual leave.
        assignment.save()
        assignment = sync_annual_leave(
            self.employee, self.leave_type, date(2025, 4, 1)
        )
        self.assertEqual(assignment.available_days, 2)
        assignment = sync_annual_leave(
            self.employee, self.leave_type, date(2025, 5, 1)
        )
        self.assertEqual(assignment.available_days, 3)  # Five earned, two used.

    def test_approved_unpaid_requests_reduce_credited_service_months(self):
        from leave.models import AvailableLeave, LeaveRequest, LeaveType

        unpaid_type = LeaveType.objects.create(
            name="Unpaid Leave", payment="unpaid", payment_type="unpaid"
        )
        for month in range(1, 5):
            LeaveRequest.objects.create(
                employee_id=self.employee,
                leave_type_id=unpaid_type,
                start_date=date(2025, month, 15),
                end_date=date(2025, month, 15),
                requested_days=1,
                status="approved",
                description="One approved unpaid day",
            )

        with patch("leave.annual_policy.timezone.localdate", return_value=date(2025, 4, 30)):
            assignment = AvailableLeave.objects.create(
                employee_id=self.employee, leave_type_id=self.leave_type
            )
        self.assertEqual(assignment.auto_entitlement_days, 4)
        self.assertEqual(assignment.available_days, 4)  # 3 / 12 * 14 rounds to 4.

    def test_anniversary_carries_unused_previous_year_without_recrediting(self):
        from leave.annual_policy import sync_annual_leave
        from leave.models import AvailableLeave

        with patch("leave.annual_policy.timezone.localdate", return_value=date(2025, 12, 31)):
            AvailableLeave.objects.create(
                employee_id=self.employee,
                leave_type_id=self.leave_type,
            )
        assignment = sync_annual_leave(
            self.employee, self.leave_type, date(2026, 1, 1)
        )
        self.assertEqual(assignment.available_days, 0)
        self.assertEqual(assignment.carryforward_days, 14)
        assignment = sync_annual_leave(
            self.employee, self.leave_type, date(2026, 1, 1)
        )
        self.assertEqual(assignment.carryforward_days, 14)

    def test_paid_annual_request_is_rejected_during_first_three_months(self):
        from leave.models import AvailableLeave, LeaveRequest

        with patch("leave.annual_policy.timezone.localdate", return_value=date(2025, 3, 31)):
            AvailableLeave.objects.create(
                employee_id=self.employee, leave_type_id=self.leave_type
            )
        request = LeaveRequest(
            employee_id=self.employee,
            leave_type_id=self.leave_type,
            start_date=date(2025, 3, 31),
            end_date=date(2025, 3, 31),
            description="Before eligibility",
        )
        with patch("leave.models.timezone.localdate", return_value=date(2025, 3, 31)):
            with self.assertRaisesMessage(ValidationError, "three months"):
                request.clean()

    def test_paid_annual_request_cannot_pass_contract_end(self):
        from leave.models import AvailableLeave, LeaveRequest

        self.employee.employee_work_info.contract_end_date = date(2025, 6, 30)
        self.employee.employee_work_info.save()
        with patch("leave.annual_policy.timezone.localdate", return_value=date(2025, 4, 1)):
            AvailableLeave.objects.create(
                employee_id=self.employee, leave_type_id=self.leave_type
            )
        request = LeaveRequest(
            employee_id=self.employee,
            leave_type_id=self.leave_type,
            start_date=date(2025, 7, 1),
            end_date=date(2025, 7, 1),
            description="After contract",
        )
        with patch("leave.models.timezone.localdate", return_value=date(2025, 4, 1)):
            with self.assertRaisesMessage(ValidationError, "employment end date"):
                request.clean()
