"""Automatic payroll must use the same calendar month rules as manual payroll."""
from datetime import date
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from employee.singapore_models import SingaporeEmployeeDetails
from horilla.testkit import make_company, make_employee
from payroll.models.models import Contract, Payslip, PayslipAutoGenerate
from payroll.scheduler import auto_payslip_generate, generate_payslip, previous_calendar_month


class PreviousMonthTests(SimpleTestCase):
    def test_run_day_does_not_move_payroll_into_two_months(self):
        for day in (1, 6, 7, 8, 31):
            self.assertEqual(previous_calendar_month(date(2026, 10, day)),
                             (date(2026, 9, 1), date(2026, 9, 30)))
        self.assertEqual(previous_calendar_month(date(2027, 1, 6)),
                         (date(2026, 12, 1), date(2026, 12, 31)))
        self.assertEqual(previous_calendar_month(date(2024, 3, 6)),
                         (date(2024, 2, 1), date(2024, 2, 29)))


class AutomaticPayrollTests(TestCase):
    def setUp(self):
        self.company = make_company("Automatic Payroll QA")
        self.company.country = "Singapore"
        self.company.save()

    def employee(self, suffix, joined=date(2025, 1, 1), end=None, status="active"):
        employee = make_employee(company=self.company, email=f"auto-{suffix}@test.example")
        employee.dob = date(1990, 1, 1)
        employee.save()
        work = employee.employee_work_info
        work.date_joining = joined
        work.contract_end_date = end
        work.save()
        Contract.objects.filter(employee_id=employee).delete()
        Contract.objects.create(employee_id=employee, contract_name="Automatic QA",
                                contract_start_date=joined, contract_end_date=end,
                                contract_status=status, wage=4000, wage_type="monthly",
                                payroll_workweek="five_day")
        SingaporeEmployeeDetails.objects.create(employee=employee, residency_status="citizen")
        return employee

    def generate(self):
        with patch("payroll.views.component_views.get_pending_attendance", return_value=[]):
            generate_payslip(date(2026, 10, 7), [self.company], False)

    def test_complete_month_cpf_and_repeat_preserve_paid_payslip(self):
        employee = self.employee("regular")
        self.generate()
        slip = Payslip.objects.get(employee_id=employee)
        self.assertEqual((slip.start_date, slip.end_date), (date(2026, 9, 1), date(2026, 9, 30)))
        self.assertEqual(slip.gross_pay, 4000)
        self.assertEqual(slip.net_pay, 3200)
        self.assertEqual(slip.payment_date, date(2026, 10, 6))
        slip.status = "paid"
        slip.save()
        self.generate()
        slip.refresh_from_db()
        self.assertEqual(Payslip.objects.filter(employee_id=employee).count(), 1)
        self.assertEqual(slip.status, "paid")

    def test_joiner_leaver_and_regular_keep_independent_periods(self):
        joiner = self.employee("joiner", joined=date(2026, 9, 15))
        leaver = self.employee("leaver", end=date(2026, 9, 18), status="terminated")
        regular = self.employee("full")
        self.generate()
        expected = {joiner.pk: (date(2026, 9, 15), date(2026, 9, 30)),
                    leaver.pk: (date(2026, 9, 1), date(2026, 9, 18)),
                    regular.pk: (date(2026, 9, 1), date(2026, 9, 30))}
        for slip in Payslip.objects.filter(employee_id__in=expected):
            self.assertEqual((slip.start_date, slip.end_date), expected[slip.employee_id_id])
        self.assertEqual(Payslip.objects.filter(employee_id__in=expected).count(), 3)
        self.generate()
        self.assertEqual(Payslip.objects.filter(employee_id__in=expected).count(), 3)

    def test_employee_validation_failure_does_not_skip_other_staff(self):
        bad = self.employee("missing-details")
        SingaporeEmployeeDetails.objects.filter(employee=bad).delete()
        good = self.employee("valid")
        with self.assertLogs("payroll.scheduler", level="ERROR"):
            self.generate()
        self.assertFalse(Payslip.objects.filter(employee_id=bad).exists())
        self.assertTrue(Payslip.objects.filter(employee_id=good).exists())

    def schedule(self, company, day):
        # Configuration save itself triggers the scheduler; keep setup inert.
        with patch("payroll.scheduler.auto_payslip_generate"):
            return PayslipAutoGenerate.objects.create(company_id=company, generate_day=day, auto_generate=True)

    def test_day_31_runs_on_february_last_day_only(self):
        self.schedule(self.company, "31")
        with patch("payroll.scheduler.generate_payslip") as generate:
            with patch("payroll.scheduler.timezone.localdate", return_value=date(2026, 2, 27)):
                auto_payslip_generate()
            generate.assert_not_called()
            with patch("payroll.scheduler.timezone.localdate", return_value=date(2026, 2, 28)):
                auto_payslip_generate()
            generate.assert_called_once_with(date=date(2026, 2, 28), companies=[self.company], all=False)

    def test_default_and_company_schedule_both_run_when_due(self):
        fallback = make_company("Default scheduled QA")
        excluded = make_company("Different schedule QA")
        self.schedule(None, "7")
        self.schedule(self.company, "7")
        self.schedule(excluded, "8")
        with patch("payroll.scheduler.timezone.localdate", return_value=date(2026, 10, 7)), \
             patch("payroll.scheduler.generate_payslip") as generate:
            auto_payslip_generate()
        self.assertEqual(generate.call_count, 1)
        args = generate.call_args.kwargs
        self.assertEqual(args["date"], date(2026, 10, 7))
        self.assertTrue(args["all"])
        self.assertIn(self.company, args["companies"])
        self.assertIn(fallback, args["companies"])
        self.assertNotIn(excluded, args["companies"])
