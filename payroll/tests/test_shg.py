"""SHG examples from CPF/CDAC/EA/SINDA/MUIS tables and payroll conflict regressions."""
import json
from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from employee.singapore_models import SingaporeContributionProfile, SingaporeEmployeeDetails
from horilla.testkit import make_company, make_employee
from payroll.models.models import Allowance, Contract, Deduction, Payslip, SalaryStructure
from payroll.shg import applicable_funds, calculate_shg, contribution, fund_wages, validate_adjustments
from payroll.views.component_views import payroll_calculation


class ShgTablesTests(SimpleTestCase):
    def test_cdac_each_ceiling_and_next_cent(self):
        for wages, amount in [(0,0),(.01,.5),(2000,.5),(2000.01,1),(3500,1),
                              (3500.01,1.5),(5000,1.5),(5000.01,2),(7500,2),(7500.01,3)]:
            with self.subTest(wages=wages):
                self.assertEqual(contribution("cdac", wages), Decimal(str(amount)))

    def test_ecf_each_ceiling_and_next_cent(self):
        for wages, amount in [(0,0),(1000,2),(1000.01,4),(1500,4),(1500.01,6),
                              (2500,6),(2500.01,9),(4000,9),(4000.01,12),(7000,12),
                              (7000.01,16),(10000,16),(10000.01,20)]:
            with self.subTest(wages=wages):
                self.assertEqual(contribution("ecf", wages), Decimal(str(amount)))

    def test_sinda_each_ceiling_and_next_cent(self):
        for wages, amount in [(0,0),(1000,1),(1000.01,3),(1500,3),(1500.01,5),
                              (2500,5),(2500.01,7),(4500,7),(4500.01,9),(7500,9),
                              (7500.01,12),(10000,12),(10000.01,18),(15000,18),(15000.01,30)]:
            with self.subTest(wages=wages):
                self.assertEqual(contribution("sinda", wages), Decimal(str(amount)))

    def test_mbmf_each_ceiling_and_next_cent(self):
        for wages, amount in [(0,0),(1000,3),(1000.01,4.5),(2000,4.5),(2000.01,6.5),
                              (3000,6.5),(3000.01,15),(4000,15),(4000.01,19.5),(6000,19.5),
                              (6000.01,22),(8000,22),(8000.01,24),(10000,24),(10000.01,26)]:
            with self.subTest(wages=wages):
                self.assertEqual(contribution("mbmf", wages), Decimal(str(amount)))

    def test_eligibility_by_declared_race_residency_and_pass(self):
        cases = [("chinese","citizen","", "no",["cdac"]),
                 ("eurasian","pr","", "no",["ecf"]),
                 ("indian","citizen","", "yes",["sinda","mbmf"]),
                 ("malay","citizen","", "yes",["mbmf"]),
                 ("indian","foreigner","EP", "no",["sinda"]),
                 ("indian","foreigner","S_PASS", "no",[]),
                 ("indian","foreigner","WORK_PERMIT", "yes",["mbmf"]),
                 ("chinese","foreigner","EP", "no",[]),
                 ("eurasian","foreigner","EP", "yes",["mbmf"]),
                 ("other","citizen","", "no",[])]
        for race, status, work_pass, muslim, expected in cases:
            p=SingaporeContributionProfile(primary_race=race,residency_status=status,
                pr_effective_date=date(2025,1,1) if status=="pr" else None,
                work_pass_type=work_pass,muslim_status=muslim)
            with self.subTest(race=race,status=status,work_pass=work_pass,muslim=muslim):
                self.assertEqual(applicable_funds(p,date(2026,9,30)),expected)

    def test_genuine_expenses_and_fund_specific_exclusions(self):
        allowances=[{"amount":100,"cpf_wage_type":"ow"},
            {"amount":200,"cpf_wage_type":"aw","shg_excluded_funds":["mbmf"]},
            {"amount":900,"cpf_wage_type":"excluded"}]
        self.assertEqual(fund_wages("cdac",4000,allowances),4300)
        self.assertEqual(fund_wages("mbmf",4000,allowances),4100)
        with self.assertRaises(ValidationError): fund_wages("cdac",0,[{"amount":100}])
        with self.assertRaises(ValidationError): contribution("cdac",-1)

    def test_adjustment_validation_rejects_missing_proof_and_invalid_money(self):
        for item in [{"mode":"fixed","amount":"1","reference":""},
                     {"mode":"fixed","amount":"NaN","reference":"proof"},
                     {"mode":"fixed","amount":"1.001","reference":"proof"},
                     {"mode":"fixed","amount":"0","reference":"proof"},
                     {"mode":"opt_out","amount":"1","reference":"proof"},
                     {"mode":"auto","reference":"proof"}]:
            with self.subTest(item=item),self.assertRaises(ValidationError):
                validate_adjustments({"cdac":item})
        with self.assertRaises(ValidationError): validate_adjustments({"unknown":{}})


class ShgPayrollTests(TestCase):
    def setUp(self):
        self.company=make_company("SHG payroll QA");self.company.country="Singapore";self.company.save()
        self.employee=make_employee(company=self.company,email="shg-qa@test.example")
        self.employee.dob=date(1990,1,1);self.employee.save()
        work=self.employee.employee_work_info;work.date_joining=date(2025,1,1);work.save()
        Contract.objects.filter(employee_id=self.employee).delete()
        self.contract=Contract.objects.create(employee_id=self.employee,contract_name="SHG QA",
            contract_start_date=date(2025,1,1),contract_status="active",wage=4000,
            wage_type="monthly",payroll_workweek="five_day",deduct_leave_from_basic_pay=True)
        self.details=SingaporeEmployeeDetails.objects.create(employee=self.employee,residency_status="citizen")

    def profile(self,**kwargs):
        defaults=dict(employee=self.employee,effective_month=date(2025,1,1),primary_race="chinese",
            muslim_status="no",residency_status="citizen",declaration_reference="QA employee declaration")
        defaults.update(kwargs)
        return SingaporeContributionProfile.objects.create(**defaults)

    def salary(self,start=date(2026,9,1),end=date(2026,9,30)):
        with patch("payroll.views.component_views.get_pending_attendance",return_value=[]):
            return payroll_calculation(self.employee,start,end)

    def allowance(self,amount,**kwargs):
        component=Allowance.objects.create(title="SHG cash",is_fixed=True,amount=amount,**kwargs)
        component.specific_employees.add(self.employee)
        return component

    def test_automatic_cdac_reduces_net_without_employer_cost(self):
        self.profile();data=self.salary()
        self.assertEqual(data["gross_pay"],4000);self.assertEqual(data["net_pay"],3198.5)
        self.assertEqual(data["statutory_shg"]["total"],1.5)
        rows=[d for d in data["post_tax_deductions"] if d["statutory_type"]=="cdac"]
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]["employer_contribution_amount"],0)
        self.assertEqual(Payslip(pay_head_data=data,gross_pay=4000).sdl_display,10)
        self.assertNotIn("primary_race",data["json_data"]);self.assertNotIn("muslim_status",data["json_data"])
        self.assertNotIn("QA employee declaration",data["json_data"])

    def test_indian_muslim_has_both_funds(self):
        self.profile(primary_race="indian",muslim_status="yes")
        data=self.salary();self.assertEqual(data["statutory_shg"]["total"],22)
        self.assertEqual(data["net_pay"],3178)

    def test_non_chinese_not_charged_cdac(self):
        self.profile(primary_race="malay",muslim_status="no")
        self.assertEqual(self.salary()["statutory_shg"]["funds"],[])

    def test_foreign_muslim_ep_has_sinda_and_mbmf_without_cpf(self):
        self.details.residency_status="foreigner";self.details.save()
        self.profile(primary_race="indian",muslim_status="yes",residency_status="foreigner",work_pass_type="EP")
        data=self.salary();self.assertIsNone(data["statutory_cpf"])
        self.assertEqual(data["net_pay"],3978)

    def test_missing_profile_blocks_generation_instead_of_silent_exemption(self):
        with self.assertRaisesMessage(ValidationError,"contribution profile"): self.salary()

    def test_reimbursements_excluded_but_cash_bonus_and_allowance_included(self):
        self.profile();self.allowance(100);self.allowance(900,cpf_wage_type="excluded")
        self.allowance(1000,cpf_wage_type="aw",one_time_date=date(2026,9,20))
        # Avoid unrelated annual AW estimate validation: foreign Muslim MBMF case.
        self.details.residency_status="foreigner";self.details.save()
        self.profile(effective_month=date(2026,9,1),residency_status="foreigner",work_pass_type="EP",muslim_status="yes")
        data=self.salary();self.assertEqual(data["statutory_shg"]["funds"][0]["wages"],5100)
        self.assertEqual(data["statutory_shg"]["total"],19.5)
        self.assertEqual(data["sdl_wages"],5100)

    def test_per_fund_allowance_exclusion_does_not_change_cpf_or_sdl(self):
        self.profile(primary_race="indian",muslim_status="yes")
        self.allowance(200,shg_excluded_funds=["mbmf"])
        data=self.salary();rows={r["fund"]:r for r in data["statutory_shg"]["funds"]}
        self.assertEqual(rows["mbmf"]["wages"],4000);self.assertEqual(rows["mbmf"]["amount"],15)
        self.assertEqual(rows["sinda"]["wages"],4200)
        self.assertEqual(data["statutory_cpf"]["ow"],4200);self.assertEqual(data["sdl_wages"],4200)

    def test_joiner_and_unpaid_days_use_earned_wages_not_contract_wage(self):
        from leave.models import LeaveRequest, LeaveType
        self.profile();self.contract.wage=5000;self.contract.save()
        work=self.employee.employee_work_info;work.date_joining=date(2026,9,7);work.save()
        unpaid=LeaveType.objects.create(name="QA unpaid",payment="unpaid",payment_type="unpaid")
        LeaveRequest.objects.create(employee_id=self.employee,leave_type_id=unpaid,
            start_date=date(2026,9,8),end_date=date(2026,9,8),status="approved",requested_days=1)
        data=self.salary();self.assertAlmostEqual(data["statutory_shg"]["funds"][0]["wages"],3863.64)
        self.assertEqual(data["statutory_shg"]["total"],1.5)

    def test_future_optout_does_not_change_prior_month(self):
        first=self.profile();self.profile(effective_month=date(2026,10,1),
            fund_adjustments={"cdac":{"mode":"opt_out","reference":"Employee form Oct"}})
        before=self.salary();after=self.salary(date(2026,10,1),date(2026,10,31))
        self.assertEqual(before["statutory_shg"]["profile_id"],first.pk)
        self.assertEqual(before["statutory_shg"]["total"],1.5);self.assertEqual(after["statutory_shg"]["total"],0)

    def test_fixed_partial_mbmf_and_voluntary_other_fund(self):
        self.profile(primary_race="malay",muslim_status="yes",fund_adjustments={
            "mbmf":{"mode":"fixed","amount":"5.00","reference":"MUIS certificate"},
            "cdac":{"mode":"voluntary","amount":"2.00","reference":"Employee authorisation"}})
        self.assertEqual(self.salary()["statutory_shg"]["total"],7)

    def test_fixed_inapplicable_fund_is_rejected(self):
        self.profile(primary_race="malay",fund_adjustments={"cdac":{"mode":"fixed","amount":"2","reference":"proof"}})
        with self.assertRaisesMessage(ValidationError,"not applicable"): self.salary()

    def test_zero_wages_do_not_create_fixed_deductions(self):
        self.profile(fund_adjustments={"cdac":{"mode":"fixed","amount":"2","reference":"proof"}})
        self.contract.wage=0;self.contract.save()
        self.assertEqual(self.salary()["statutory_shg"]["total"],0)

    def test_student_cpf_and_mbmf_exemptions_are_independent(self):
        self.contract.cpf_exempt=True;self.contract.cpf_exemption_reason="Institution evidence QA";self.contract.save()
        self.profile(primary_race="indian",muslim_status="yes",student_cpf_exempt=True,
            student_exempt_from=date(2026,8,1),student_exempt_until=date(2026,12,31),student_exemption_reference="Institution evidence QA")
        data=self.salary();self.assertEqual(data["statutory_shg"]["total"],15)
        self.profile(primary_race="indian",muslim_status="yes",student_cpf_exempt=True,student_mbmf_exempt=True,
            student_exempt_from=date(2026,8,1),student_exempt_until=date(2026,12,31),student_exemption_reference="MUIS qualifying student evidence")
        self.assertEqual(self.salary()["statutory_shg"]["total"],0)

    def test_student_requires_evidence_dates_and_aligned_cpf_contract(self):
        with self.assertRaises(ValidationError): self.profile(student_cpf_exempt=True)
        self.profile(student_cpf_exempt=True,student_exempt_from=date(2026,8,1),
            student_exempt_until=date(2026,12,31),student_exemption_reference="Evidence QA")
        with self.assertRaisesMessage(ValidationError,"on the payroll contract"): self.salary()

    def test_partial_student_transition_requires_review(self):
        self.profile(student_mbmf_exempt=True,muslim_status="yes",student_exempt_from=date(2026,9,15),
            student_exempt_until=date(2026,12,31),student_exemption_reference="Evidence QA")
        with self.assertRaisesMessage(ValidationError,"changes within"): self.salary()

    def test_expired_student_cpf_exemption_cannot_silently_continue(self):
        self.contract.cpf_exempt=True;self.contract.cpf_exemption_reason="Institution QA";self.contract.save()
        self.profile(student_cpf_exempt=True,student_exempt_from=date(2026,6,1),
            student_exempt_until=date(2026,8,31),student_exemption_reference="Institution QA")
        with self.assertRaisesMessage(ValidationError,"beyond"): self.salary()

    def test_pr_transition_uses_post_pr_wages_for_cdac_and_full_wages_for_mbmf(self):
        self.details.residency_status="pr";self.details.pr_effective_date=date(2026,9,7);self.details.save()
        self.profile(effective_month=date(2026,9,1),residency_status="pr",pr_effective_date=date(2026,9,7),muslim_status="yes")
        data=self.salary();rows={r["fund"]:r for r in data["statutory_shg"]["funds"]}
        self.assertEqual(rows["cdac"]["wages"],3272.73);self.assertEqual(rows["cdac"]["amount"],1)
        self.assertEqual(rows["mbmf"]["wages"],4000);self.assertEqual(rows["mbmf"]["amount"],15)
        self.assertEqual(data["sdl_wages"],4000)

    def test_indian_ep_to_pr_has_full_month_sinda(self):
        self.profile(primary_race="indian",residency_status="foreigner",work_pass_type="EP")
        self.profile(effective_month=date(2026,9,1),primary_race="indian",residency_status="pr",pr_effective_date=date(2026,9,7))
        self.details.residency_status="pr";self.details.pr_effective_date=date(2026,9,7);self.details.save()
        self.assertEqual(self.salary()["statutory_shg"]["funds"][0]["wages"],4000)

    def test_indian_s_pass_to_pr_has_post_pr_sinda_only(self):
        self.profile(primary_race="indian",residency_status="foreigner",work_pass_type="S_PASS")
        self.profile(effective_month=date(2026,9,1),primary_race="indian",residency_status="pr",pr_effective_date=date(2026,9,7))
        self.details.residency_status="pr";self.details.pr_effective_date=date(2026,9,7);self.details.save()
        self.assertEqual(self.salary()["statutory_shg"]["funds"][0]["wages"],3272.73)

    def test_unknown_pre_pr_pass_is_not_inferred(self):
        self.profile(effective_month=date(2026,9,1),primary_race="indian",residency_status="pr",pr_effective_date=date(2026,9,7))
        with self.assertRaisesMessage(ValidationError,"pre-PR"): self.salary()

    def test_legacy_shg_deductions_do_not_duplicate_any_compensation_channel(self):
        self.profile();structure=SalaryStructure.objects.create(title="Legacy SHG QA")
        self.contract.salary_structure_id=structure;self.contract.save()
        for fund in ("cdac","ecf","sinda","mbmf"):
            for channel in (None,"basic_pay","gross_pay","net_pay"):
                component=Deduction.objects.create(title="Legacy "+fund,statutory_type=fund,is_fixed=True,
                    amount=50,is_pretax=False,update_compensation=channel,only_show_under_employee=True)
                component.specific_employees.add(self.employee);structure.deductions.add(component)
        advance=Deduction.objects.create(title="Advance",is_fixed=True,amount=100,update_compensation="net_pay")
        advance.specific_employees.add(self.employee)
        data=self.salary();self.assertEqual(data["gross_pay"],4000);self.assertEqual(data["net_pay"],3098.5)
        self.assertEqual(data["basic_pay_deductions"],[]);self.assertEqual(data["gross_pay_deductions"],[])
        self.assertFalse(any(d["title"].startswith("Legacy") for d in data["post_tax_deductions"]+data["net_deductions"]))

    def test_empty_structure_cannot_disable_automatic_fund(self):
        self.profile();self.contract.salary_structure_id=SalaryStructure.objects.create(title="Empty QA");self.contract.save()
        self.assertEqual(self.salary()["statutory_shg"]["total"],1.5)

    def test_draft_recalculation_is_idempotent_and_paid_snapshot_unchanged(self):
        self.profile();data=self.salary()
        slip=Payslip.objects.create(employee_id=self.employee,start_date=data["start_date"],end_date=data["end_date"],
            pay_head_data=json.loads(data["json_data"]),gross_pay=data["gross_pay"],net_pay=data["net_pay"],status="draft")
        self.profile(fund_adjustments={"cdac":{"mode":"opt_out","reference":"Employee form"}})
        original=slip.pay_head_data
        with patch("payroll.views.component_views.get_pending_attendance",return_value=[]):
            call_command("recalculate_draft_payslip",id=slip.pk,apply=False,stdout=StringIO())
            slip.refresh_from_db();self.assertEqual(slip.pay_head_data,original)
            for _ in range(2): call_command("recalculate_draft_payslip",id=slip.pk,apply=True,stdout=StringIO())
        slip.refresh_from_db();self.assertEqual(slip.net_pay,3200);self.assertEqual(slip.pay_head_data["statutory_shg"]["total"],0)
        slip.status="paid";slip.save();snapshot=slip.pay_head_data
        self.profile()
        with self.assertRaisesMessage(CommandError,"Only draft"):
            call_command("recalculate_draft_payslip",id=slip.pk,apply=True,stdout=StringIO())
        slip.refresh_from_db();self.assertEqual(slip.pay_head_data,snapshot)

    def test_monthly_consolidation_also_applies_without_cpf(self):
        self.details.residency_status="foreigner";self.details.save()
        self.profile(residency_status="foreigner",work_pass_type="EP",muslim_status="yes")
        Payslip.objects.create(employee_id=self.employee,start_date=date(2026,9,1),end_date=date(2026,9,15),pay_head_data={})
        with self.assertRaisesMessage(ValidationError,"Consolidate"): self.salary()

    def test_non_singapore_payroll_retains_previous_behaviour(self):
        self.details.delete();self.company.country="US";self.company.save()
        self.assertIsNone(self.salary()["statutory_shg"])
