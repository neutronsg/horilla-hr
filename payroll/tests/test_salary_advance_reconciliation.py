import io
import json
from datetime import date
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.http import QueryDict
from django.test import TestCase

from horilla.testkit import make_company, make_employee
from payroll.advances import annotate_deduction_sources, manual_advance_conflicts
from payroll.forms.component_forms import DeductionForm, LoanAccountForm
from payroll.models.models import Contract, Deduction, LoanAccount, Payslip
from payroll.views.component_views import payroll_calculation
from payroll.statutory import eligible_deductions


class SalaryAdvanceReconciliationTests(TestCase):
    def setUp(self):
        self.employee = make_employee(company=make_company("Advance QA"), email="advance-qa@example.test")
        self.loan = LoanAccount.objects.create(employee_id=self.employee, title="Salary advance", type="advanced_salary",
            loan_amount=2100, installments=1, provided_date=date(2026, 9, 4), installment_start_date=date(2026, 9, 7))
        self.repayment = self.loan.deduction_ids.get()
        self.manual = Deduction.objects.create(title="Advances", is_fixed=True, amount=2100,
            update_compensation="net_pay", one_time_date=date(2026, 9, 7), include_active_employees=False)
        self.manual.specific_employees.add(self.employee)

    def slip(self, duplicate=False, status="draft"):
        data = {"gross_pay": 5000, "net_pay": 800 if duplicate else 2900, "total_deductions": 4200 if duplicate else 2100,
            "net_deductions": [{"deduction_id": self.manual.pk, "title": "Advances", "amount": 2100}],
            "post_tax_deductions": [{"deduction_id": self.repayment.pk, "title": self.repayment.title, "amount": 2100}] if duplicate else []}
        return Payslip.objects.create(employee_id=self.employee, start_date=date(2026, 9, 7), end_date=date(2026, 9, 30),
            gross_pay=5000, net_pay=data["net_pay"], deduction=data["total_deductions"], pay_head_data=data, status=status)

    def reconcile(self, apply=False):
        output = io.StringIO()
        call_command("reconcile_salary_advance", loan_id=self.loan.pk, manual_deduction_id=self.manual.pk, apply=apply, stdout=output)
        return json.loads(output.getvalue())

    def test_repayment_is_post_tax_and_source_is_the_advance_record(self):
        self.assertFalse(self.repayment.is_pretax)
        data = annotate_deduction_sources({"post_tax_deductions": [{"deduction_id": self.repayment.pk}]})
        self.assertEqual(data["post_tax_deductions"][0]["loan_account_id"], self.loan.pk)

    def test_preview_does_not_change_deduction_or_draft(self):
        slip = self.slip(True)
        report = self.reconcile()
        self.manual.refresh_from_db(); slip.refresh_from_db()
        self.assertTrue(self.manual.is_active)
        self.assertEqual(slip.net_pay, 800)
        self.assertEqual(report["payslips"][0]["new_net"], 2900)

    def test_duplicate_is_removed_once_and_archived_record_is_retained(self):
        slip = self.slip(True)
        self.reconcile(True)
        self.manual.refresh_from_db(); slip.refresh_from_db()
        self.assertFalse(self.manual.is_active)
        self.assertEqual(slip.net_pay, 2900); self.assertEqual(slip.deduction, 2100)
        self.assertEqual(slip.pay_head_data["net_deductions"], [])
        self.assertEqual(slip.installment_ids.get(), self.repayment)
        self.assertEqual(slip.pay_head_data["post_tax_deductions"][0]["loan_account_id"], self.loan.pk)
        self.assertFalse(eligible_deductions(Deduction.objects.all(), self.employee).filter(pk=self.manual.pk).exists())
        self.reconcile(True); slip.refresh_from_db(); self.assertEqual(slip.net_pay, 2900)

    def test_single_existing_manual_repayment_is_relinked_without_changing_pay(self):
        slip = self.slip()
        self.reconcile(True); slip.refresh_from_db()
        self.assertEqual(slip.net_pay, 2900)
        self.assertEqual(slip.pay_head_data["post_tax_deductions"][0]["deduction_id"], self.repayment.pk)

    def test_finalized_or_sent_payslips_are_not_rewritten(self):
        slip = self.slip(status="paid")
        with self.assertRaisesMessage(CommandError, "finalized or sent"):
            self.reconcile(True)
        self.manual.refresh_from_db(); self.assertTrue(self.manual.is_active)
        slip.status = "draft"; slip.sent_to_employee = True; slip.save()
        with self.assertRaises(CommandError): self.reconcile(True)

    def test_different_amount_or_employee_is_not_automatically_merged(self):
        self.manual.amount = 2000; self.manual.save()
        with self.assertRaisesMessage(CommandError, "not an exact"):
            self.reconcile(True)
        self.assertFalse(manual_advance_conflicts(self.employee, date(2026, 9, 7), 2100).exists())

    def test_new_payroll_applies_one_repayment_without_reducing_earned_wage_bases(self):
        Contract.objects.filter(employee_id=self.employee).delete()
        Contract.objects.create(employee_id=self.employee, contract_name="Advance QA", contract_status="active",
            contract_start_date=date(2026, 9, 7), wage=8400, wage_type="monthly", payroll_workweek="five_day")
        self.reconcile(True)
        with patch("payroll.views.component_views.get_pending_attendance", return_value=[]):
            data = payroll_calculation(self.employee, date(2026, 9, 7), date(2026, 9, 30), month_summary={"present": 18, "absent": 0})
        self.assertAlmostEqual(data["gross_pay"] - data["net_pay"], 2100)
        self.assertAlmostEqual(data["total_deductions"], 2100)
        self.assertEqual(data["pretax_deductions"], [])
        self.assertEqual(data["net_deductions"], [])
        self.assertAlmostEqual(data["taxable_gross_pay"], data["gross_pay"])
        self.assertEqual(data["sdl_wages"], round(data["gross_pay"], 2))
        self.assertEqual(list(data["installments"]), [self.repayment])

    def test_advance_form_blocks_duplicate_loan_and_conflicting_manual_entry(self):
        data = {"employee_id": self.employee.pk, "title": "Salary advance", "type": "advanced_salary", "loan_amount": "2100",
            "installments": "1", "provided_date": "2026-09-04", "installment_start_date": "2026-09-07"}
        form = LoanAccountForm(data)
        self.assertFalse(form.is_valid())
        self.assertIn("already recorded", str(form.non_field_errors()))
        self.assertIn("manual advance deduction", str(form.non_field_errors()))

    def test_manual_form_blocks_a_second_repayment_for_an_existing_advance(self):
        data = QueryDict(mutable=True)
        data.update({"title": "Advances", "is_fixed": "on", "amount": "2100", "update_compensation": "net_pay", "one_time_date": "2026-09-07"})
        data.setlist("specific_employees", [str(self.employee.pk)])
        form = DeductionForm(data)
        self.assertFalse(form.is_valid())
        self.assertIn("already has a repayment", str(form.non_field_errors()))
