from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from employee.contributions import ContributionProfileForm
from employee.singapore_models import SingaporeContributionProfile, SingaporeEmployeeDetails
from horilla.testkit import make_company, make_employee
from payroll.models.models import Contract
from payroll.shg import calculate_shg


class FundConfigurationTests(TestCase):
    def setUp(self):
        company = make_company("Fund selection QA", country="Singapore")
        self.employee = make_employee(company=company, email="fund-selection@test.example")
        self.details = SingaporeEmployeeDetails.objects.create(employee=self.employee, residency_status="foreigner", work_pass_type="S_PASS")
        Contract.objects.filter(employee_id=self.employee).delete()
        self.contract = Contract.objects.create(employee_id=self.employee, contract_name="QA funds", contract_start_date=date(2025,1,1), contract_status="active", wage=4000, wage_type="monthly", payroll_workweek="five_day")

    def data(self, **changes):
        data = {"configuration_version":"funds-v3", "effective_month":"2026-09", "use_start_month":"on", "start_month":"2026-09", "declaration_reference":"Verified fund eligibility"}
        data.update({f"{fund}_mode":"not_applicable" for fund in ("cdac","ecf","sinda","mbmf")})
        data.update(changes)
        return data

    def form(self, **changes):
        return ContributionProfileForm(self.data(**changes), details=self.details,
            instance=SingaporeContributionProfile(employee=self.employee))

    def calculation(self, profile):
        return calculate_shg(self.employee,self.contract,date(2026,9,1),date(2026,9,30),4000,[])

    def test_four_not_applicable_funds_pass_with_no_demographic_values(self):
        form=self.form();self.assertTrue(form.is_valid(),form.errors);profile=form.save()
        self.assertEqual(profile.primary_race,"");self.assertEqual(profile.muslim_status,"")
        self.assertEqual(self.calculation(profile)["total"],0)
        self.assertEqual(self.calculation(profile)["funds"],[])

    def test_explicit_mbmf_without_religion_question_charges_correct_rate(self):
        form=self.form(mbmf_mode="auto");self.assertTrue(form.is_valid(),form.errors)
        data=self.calculation(form.save());self.assertEqual(data["total"],15)
        self.assertEqual([row["fund"] for row in data["funds"]],["mbmf"])

    def test_dual_sinda_mbmf_ep_and_approved_amount(self):
        self.details.work_pass_type="EP";self.details.save()
        form=self.form(sinda_mode="auto",mbmf_mode="fixed",mbmf_amount="5",mbmf_reference="Approved MBMF certificate")
        self.assertTrue(form.is_valid(),form.errors);self.assertEqual(self.calculation(form.save())["total"],12)

    def test_applicable_cdac_and_ecf_use_existing_citizen_residency(self):
        self.details.residency_status="citizen";self.details.work_pass_type="";self.details.save()
        for fund,expected in (("cdac",1.5),("ecf",9),("sinda",7)):
            form=self.form(**{f"{fund}_mode":"auto"});self.assertTrue(form.is_valid(),form.errors)
            self.assertEqual(self.calculation(form.save())["total"],expected)

    def test_foreign_statutory_cdac_ecf_and_sinda_s_pass_are_rejected(self):
        for fund in ("cdac","ecf","sinda"):
            form=self.form(**{f"{fund}_mode":"auto"});self.assertFalse(form.is_valid())
            self.assertTrue(form.non_field_errors())

    def test_optout_fixed_and_voluntary_require_evidence(self):
        for mode in ("opt_out","fixed","voluntary"):
            form=self.form(mbmf_mode=mode);self.assertFalse(form.is_valid());self.assertIn("mbmf_reference",form.errors)
        form=self.form(mbmf_mode="opt_out",mbmf_reference="Approved opt-out")
        self.assertTrue(form.is_valid(),form.errors);self.assertEqual(self.calculation(form.save())["total"],0)
        form=self.form(cdac_mode="voluntary",cdac_amount="3",cdac_reference="Employee authorised request")
        self.assertTrue(form.is_valid(),form.errors);self.assertEqual(self.calculation(form.save())["total"],3)

    def test_blank_settings_and_stale_browser_forms_do_not_silently_enable_funds(self):
        for changes in ({"mbmf_mode":""},{"configuration_version":""}):
            self.assertFalse(self.form(**changes).is_valid())

    def test_student_exemption_requires_dates_and_evidence(self):
        self.assertFalse(self.form(mbmf_mode="student_exempt").is_valid())
        form=self.form(mbmf_mode="student_exempt",student_exempt_from="2026-09-01",student_exempt_until="2026-09-30",student_exemption_reference="Verified MUIS evidence")
        self.assertTrue(form.is_valid(),form.errors);self.assertEqual(self.calculation(form.save())["total"],0)

    def test_missing_employment_and_pr_date_after_salary_month_are_form_errors(self):
        self.details.residency_status="";self.details.save()
        form=ContributionProfileForm(self.data(),details=self.details,instance=SingaporeContributionProfile(employee=self.employee))
        self.assertFalse(form.is_valid());self.assertTrue(form.non_field_errors())
        self.details.residency_status="pr";self.details.work_pass_type="";self.details.pr_effective_date=date(2026,10,1)
        form=self.form();self.assertFalse(form.is_valid());self.assertTrue(form.non_field_errors())

    def test_model_rejects_incomplete_and_non_boolean_fund_selection(self):
        for selection in ({},{"mbmf":False},{"cdac":0,"ecf":False,"sinda":False,"mbmf":False}):
            record=SingaporeContributionProfile(employee=self.employee,effective_month=date(2026,9,1),residency_status="foreigner",work_pass_type="S_PASS",declaration_reference="HR verified",fund_selection=selection)
            with self.assertRaises(ValidationError):record.save()

    def test_pr_transition_uses_prior_explicit_sinda_setting(self):
        selection={"cdac":False,"ecf":False,"sinda":True,"mbmf":False}
        SingaporeContributionProfile.objects.create(employee=self.employee,effective_month=date(2026,8,1),
            residency_status="foreigner",work_pass_type="EP",declaration_reference="Verified August setup",fund_selection=selection)
        self.details.residency_status="pr";self.details.work_pass_type="";self.details.pr_effective_date=date(2026,9,15);self.details.save()
        form=self.form(sinda_mode="auto");self.assertTrue(form.is_valid(),form.errors);profile=form.save()
        data=calculate_shg(self.employee,self.contract,date(2026,9,1),date(2026,9,30),4000,[],wages_from=lambda _: (2000,[]))
        self.assertEqual(data["funds"][0]["wages"],4000);self.assertEqual(data["total"],7)

    def test_pr_transition_without_prior_sinda_recomputes_eligible_wages(self):
        SingaporeContributionProfile.objects.create(employee=self.employee,effective_month=date(2026,8,1),
            residency_status="foreigner",work_pass_type="S_PASS",declaration_reference="Verified August setup",
            fund_selection={"cdac":False,"ecf":False,"sinda":False,"mbmf":False})
        self.details.residency_status="pr";self.details.work_pass_type="";self.details.pr_effective_date=date(2026,9,15);self.details.save()
        form=self.form(sinda_mode="auto");self.assertTrue(form.is_valid(),form.errors);form.save()
        data=calculate_shg(self.employee,self.contract,date(2026,9,1),date(2026,9,30),4000,[],wages_from=lambda _: (2000,[]))
        self.assertEqual(data["funds"][0]["wages"],2000);self.assertEqual(data["total"],5)
