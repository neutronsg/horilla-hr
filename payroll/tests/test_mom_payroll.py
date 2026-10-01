import json
from datetime import date, time
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from base.models import EmployeeShift, EmployeeShiftDay, EmployeeShiftSchedule, Holidays
from horilla.testkit import make_company, make_employee
from payroll.calendar import working_day_weights
from payroll.methods.methods import compute_salary_on_period
from payroll.models.models import Contract, Deduction, Payslip, SalaryStructure
from payroll.views.component_views import payroll_calculation


class MomPayrollTests(TestCase):
    def setUp(self):
        self.company = make_company("MOM payroll")
        self.employee = make_employee(company=self.company, email="mom-payroll@test.example")
        work = self.employee.employee_work_info
        work.date_joining = date(2026, 9, 7)
        work.save()
        Contract.objects.filter(employee_id=self.employee).delete()
        self.contract = Contract.objects.create(
            contract_name="Monthly", employee_id=self.employee,
            contract_start_date=date(2026, 9, 7), contract_status="active",
            wage=8400, wage_type="monthly", payroll_workweek="five_day",
            deduct_leave_from_basic_pay=True, calculate_daily_leave_amount=True,
        )

    def calculate(self, summary=None):
        return compute_salary_on_period(self.employee, date(2026, 9, 1), date(2026, 9, 30), month_summary=summary)

    def test_carlos_working_day_proration_and_joining_date_clipping(self):
        data = self.calculate()
        self.assertAlmostEqual(data["basic_pay"], 8400 * 18 / 22)
        self.assertEqual(data["paid_days"], 18)
        self.assertEqual(data["month_data"][0]["working_days_on_month"], 22)
        self.assertEqual(data["effective_start_date"], date(2026, 9, 7))

    def test_attendance_path_does_not_pay_full_month_for_mid_month_joiner(self):
        data = self.calculate({"present": 18, "week_off": 6, "absent": 0})
        self.assertAlmostEqual(data["basic_pay"], 8400 * 18 / 22)

    def test_payroll_attendance_summary_excludes_unscheduled_weekends(self):
        from attendance.views.summary import build_monthly_summary
        from employee.models import Employee
        rows, _, _ = build_monthly_summary(date(2026, 9, 7), date(2026, 9, 30),
            Employee.objects.filter(pk=self.employee.pk), payroll_schedule=True)
        self.assertEqual(rows[0]["absent"], 18)
        self.assertEqual(rows[0]["week_off"], 6)
        self.assertEqual(rows[0]["total_working"], 18)

    def test_half_day_unpaid_leave_uses_mom_rate(self):
        from leave.models import LeaveRequest, LeaveType
        unpaid = LeaveType.objects.create(name="Unpaid", payment="unpaid", payment_type="unpaid")
        LeaveRequest.objects.create(employee_id=self.employee, leave_type_id=unpaid,
            start_date=date(2026, 9, 8), end_date=date(2026, 9, 8),
            start_date_breakdown="first_half", end_date_breakdown="first_half",
            status="approved", description="Half day", requested_days=0.5)
        self.assertAlmostEqual(self.calculate()["basic_pay"], 8400 * 17.5 / 22)

    def test_unpaid_attendance_day_is_deducted_once_and_advance_total_reconciles(self):
        advance = Deduction.objects.create(title="Advances", is_fixed=True, amount=2100, update_compensation="net_pay")
        advance.specific_employees.add(self.employee)
        with patch("payroll.views.component_views.get_pending_attendance", return_value=[]):
            data = payroll_calculation(self.employee, date(2026, 9, 1), date(2026, 9, 30), month_summary={"present": 17, "absent": 1})
        self.assertAlmostEqual(data["gross_pay"], 8400 * 17 / 22)
        self.assertAlmostEqual(data["net_pay"], 8400 * 17 / 22 - 2100)
        self.assertAlmostEqual(data["total_deductions"], 2100)

    def test_contract_end_caps_salary(self):
        self.contract.contract_end_date = date(2026, 9, 18)
        Contract.objects.filter(pk=self.contract.pk).update(contract_end_date=date(2026, 9, 18))
        self.assertAlmostEqual(self.calculate()["basic_pay"], 8400 * 10 / 22)

    def test_six_day_workweek(self):
        self.contract.payroll_workweek = "six_day"
        self.contract.save()
        self.assertAlmostEqual(self.calculate()["basic_pay"], 8400 * 21 / 26)

    def test_paid_holiday_is_included_in_salary_denominator(self):
        Holidays.objects.create(name="Paid holiday", start_date=date(2026, 9, 8), end_date=date(2026, 9, 8))
        self.assertAlmostEqual(self.calculate()["basic_pay"], 8400 * 18 / 22)

    def test_half_day_shift_schedule(self):
        shift = EmployeeShift.objects.create(employee_shift="Half Saturday")
        self.contract.shift = shift
        self.contract.payroll_workweek = ""
        self.contract.save()
        for day in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday"):
            day_obj, _ = EmployeeShiftDay.objects.get_or_create(day=day)
            EmployeeShiftSchedule.objects.create(shift_id=shift, day=day_obj,
                minimum_working_hour="04:00" if day == "saturday" else "08:00", start_time=time(9), end_time=time(17))
        weights = working_day_weights(self.employee, self.contract, date(2026, 9, 1), date(2026, 9, 30))
        self.assertEqual(sum(weights.values()), 24)
        self.assertAlmostEqual(self.calculate()["basic_pay"], 8400 * 19.5 / 24)

    def test_missing_schedule_is_actionable_validation_error(self):
        self.contract.payroll_workweek = ""
        self.contract.save()
        with self.assertRaisesMessage(ValidationError, "Set a payroll workweek"):
            self.calculate()

    def test_intern_exemption_overrides_direct_cpf_and_cdac_only(self):
        self.contract.cpf_exempt = True
        self.contract.cpf_exemption_reason = "Institution-approved internship, confirmed by HR"
        self.contract.save()
        for title, code, amount in (("CPF", "cpf", 260), ("CDAC", "cdac", 0.5), ("Other", "none", 10)):
            component = Deduction.objects.create(title=title, statutory_type=code, is_fixed=True, amount=amount, is_pretax=False)
            component.specific_employees.add(self.employee)
        with patch("payroll.views.component_views.get_pending_attendance", return_value=[]):
            data = payroll_calculation(self.employee, date(2026, 9, 7), date(2026, 9, 30))
        self.assertEqual([d["title"] for d in data["post_tax_deductions"]], ["Other"])
        self.assertAlmostEqual(data["total_deductions"], 10)

    def test_nonexempt_employee_retains_cpf(self):
        component = Deduction.objects.create(title="CPF", statutory_type="cpf", is_fixed=True, amount=260)
        component.specific_employees.add(self.employee)
        with patch("payroll.views.component_views.get_pending_attendance", return_value=[]):
            data = payroll_calculation(self.employee, date(2026, 9, 7), date(2026, 9, 30))
        self.assertAlmostEqual(data["total_deductions"], 260)

    def test_exemption_needs_reason_and_sdl_is_snapshot_based(self):
        self.contract.cpf_exempt = True
        with self.assertRaisesMessage(ValidationError, "Record the exemption basis"):
            self.contract.clean()
        self.assertEqual(Payslip(gross_pay=1300, pay_head_data={"sdl_exempt": True}).sdl_display, 0)
        self.assertEqual(Payslip(gross_pay=1300, pay_head_data={}).sdl_display, 3.25)

    def test_empty_structure_discloses_direct_deductions(self):
        structure = SalaryStructure.objects.create(title="Intern")
        self.contract.salary_structure_id = structure
        self.contract.save()
        component = Deduction.objects.create(title="CPF", statutory_type="cpf", is_fixed=True, amount=260)
        component.specific_employees.add(self.employee)
        with patch("horilla_views.cbv_methods.get_all_context_variables", return_value={}):
            html = structure.get_additional_deductions_detail_col()
        self.assertIn("CPF", html)
        self.assertIn("assigned directly to employee", html)

    def test_empty_structure_is_authoritative_without_inferred_exemption(self):
        self.contract.salary_structure_id = SalaryStructure.objects.create(title="No deductions")
        self.contract.save()
        component = Deduction.objects.create(title="Old recurring CPF", statutory_type="cpf", is_fixed=True, amount=260)
        component.specific_employees.add(self.employee)
        advance = Deduction.objects.create(title="Advance", amount=100, update_compensation="net_pay")
        advance.specific_employees.add(self.employee)
        with patch("payroll.views.component_views.get_pending_attendance", return_value=[]):
            data = payroll_calculation(self.employee, date(2026, 9, 7), date(2026, 9, 30))
        self.assertFalse(self.contract.cpf_exempt)
        self.assertAlmostEqual(data["total_deductions"], 100)
        self.assertEqual(data["pretax_deductions"], [])

    def test_selected_structure_keeps_its_configured_cpf(self):
        structure = SalaryStructure.objects.create(title="CPF structure")
        self.contract.salary_structure_id = structure
        self.contract.save()
        component = Deduction.objects.create(title="CPF", statutory_type="cpf", is_fixed=True, amount=260)
        structure.add_deduction(component)
        with patch("payroll.views.component_views.get_pending_attendance", return_value=[]):
            data = payroll_calculation(self.employee, date(2026, 9, 7), date(2026, 9, 30))
        self.assertAlmostEqual(data["total_deductions"], 260)

    def test_recalculation_refuses_paid_payslip(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        slip = Payslip.objects.create(employee_id=self.employee, start_date=date(2026, 9, 7), end_date=date(2026, 9, 30), pay_head_data={}, status="paid")
        with self.assertRaisesMessage(CommandError, "Only draft"):
            call_command("recalculate_draft_payslip", id=slip.pk, apply=True)
