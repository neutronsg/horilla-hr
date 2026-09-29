"""MOM sick leave milestones, calendar resets, and linked caps."""

from datetime import date
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from leave.sick_entitlement import calculate_sick_entitlement


class SickEntitlementExamples(SimpleTestCase):
    def test_mom_milestones_from_joining_date(self):
        joined = date(2023, 2, 13)
        examples = [
            (date(2023, 5, 12), 0, 0),
            (date(2023, 5, 13), 5, 15),
            (date(2023, 6, 13), 8, 30),
            (date(2023, 7, 13), 11, 45),
            (date(2023, 8, 13), 14, 60),
        ]
        for as_of, outpatient, hospitalisation in examples:
            with self.subTest(as_of=as_of):
                self.assertEqual(
                    calculate_sick_entitlement(
                        joined, as_of,
                        policy="outpatient_sick", configured_days=12,
                    ).earned_days,
                    outpatient,
                )
                self.assertEqual(
                    calculate_sick_entitlement(
                        joined, as_of,
                        policy="hospitalisation", configured_days=60,
                    ).earned_days,
                    hospitalisation,
                )

    def test_usage_window_resets_after_six_months_across_new_year(self):
        joined = date(2024, 8, 7)
        before = calculate_sick_entitlement(
            joined, date(2025, 1, 7),
            policy="hospitalisation", configured_days=60,
        )
        after = calculate_sick_entitlement(
            joined, date(2025, 2, 7),
            policy="hospitalisation", configured_days=60,
        )
        self.assertEqual((before.earned_days, before.usage_start), (45, joined))
        self.assertEqual((after.earned_days, after.usage_start), (60, date(2025, 1, 1)))

    def test_contract_end_caps_service(self):
        result = calculate_sick_entitlement(
            date(2025, 1, 1), date(2025, 12, 31),
            policy="outpatient_sick", configured_days=14,
            employment_end_date=date(2025, 4, 30),
        )
        self.assertEqual(result.earned_days, 8)


class SickBalanceIntegrationTests(TestCase):
    def setUp(self):
        from horilla.testkit import make_company, make_employee
        from leave.models import LeaveType

        company = make_company("Sick Leave Co")
        self.employee = make_employee(company=company, email="sick@test.horilla")
        self.employee.employee_work_info.date_joining = date(2024, 8, 7)
        self.employee.employee_work_info.save()
        self.outpatient = LeaveType.objects.create(
            name="Outpatient Sick Leave", total_days=12,
            auto_leave_policy="outpatient_sick",
        )
        self.hospitalisation = LeaveType.objects.create(
            name="Hospitalisation Leave", total_days=60,
            auto_leave_policy="hospitalisation",
        )

    def test_outpatient_usage_reduces_both_balances(self):
        from leave.sick_policy import sync_sick_leave
        from leave.models import AvailableLeave, LeaveRequest

        with patch("leave.sick_policy.timezone.localdate", return_value=date(2025, 2, 7)):
            outpatient = AvailableLeave.objects.create(
                employee_id=self.employee, leave_type_id=self.outpatient,
            )
            hospitalisation = AvailableLeave.objects.create(
                employee_id=self.employee, leave_type_id=self.hospitalisation,
            )
        self.assertEqual(outpatient.available_days, 14)
        self.assertEqual(hospitalisation.available_days, 60)

        LeaveRequest.objects.create(
            employee_id=self.employee, leave_type_id=self.outpatient,
            start_date=date(2025, 1, 8), end_date=date(2025, 1, 9),
            requested_days=2, status="approved", description="MC",
        )
        outpatient = sync_sick_leave(self.employee, self.outpatient, date(2025, 2, 7))
        hospitalisation = sync_sick_leave(
            self.employee, self.hospitalisation, date(2025, 2, 7)
        )
        self.assertEqual(outpatient.available_days, 12)
        self.assertEqual(hospitalisation.available_days, 58)
        self.assertEqual(
            sync_sick_leave(self.employee, self.hospitalisation, date(2025, 2, 7)).available_days,
            58,
        )

    def test_mom_cross_year_example(self):
        from leave.sick_policy import sync_sick_leave
        from leave.models import AvailableLeave, LeaveRequest

        with patch("leave.sick_policy.timezone.localdate", return_value=date(2024, 12, 7)):
            AvailableLeave.objects.create(
                employee_id=self.employee, leave_type_id=self.hospitalisation,
            )
        for start, end, days in [
            (date(2024, 12, 8), date(2024, 12, 20), 10),
            (date(2025, 1, 8), date(2025, 1, 13), 4),
        ]:
            request = LeaveRequest.objects.create(
                employee_id=self.employee, leave_type_id=self.hospitalisation,
                start_date=start, end_date=end, requested_days=days,
                status="approved", description="Hospitalisation",
            )
            # The example assumes a five-day week. Keep MOM's working-day
            # totals after Horilla's generic calendar-day save hook runs.
            LeaveRequest.objects.filter(pk=request.pk).update(requested_days=days)
        before_reset = sync_sick_leave(
            self.employee, self.hospitalisation, date(2025, 1, 7)
        )
        after_reset = sync_sick_leave(
            self.employee, self.hospitalisation, date(2025, 2, 7)
        )
        self.assertEqual(before_reset.available_days, 31)
        self.assertEqual(after_reset.available_days, 56)

    def test_hospital_use_also_caps_new_outpatient_requests(self):
        from leave.sick_policy import sync_sick_leave
        from leave.models import AvailableLeave, LeaveRequest

        with patch("leave.sick_policy.timezone.localdate", return_value=date(2025, 2, 7)):
            AvailableLeave.objects.create(
                employee_id=self.employee, leave_type_id=self.outpatient,
            )
            AvailableLeave.objects.create(
                employee_id=self.employee, leave_type_id=self.hospitalisation,
            )
        LeaveRequest.objects.create(
            employee_id=self.employee, leave_type_id=self.hospitalisation,
            start_date=date(2025, 2, 10), end_date=date(2025, 4, 10),
            requested_days=60, status="approved", description="Hospitalisation",
        )
        outpatient = sync_sick_leave(
            self.employee, self.outpatient, date(2025, 2, 7)
        )
        self.assertEqual(outpatient.available_days, 0)
