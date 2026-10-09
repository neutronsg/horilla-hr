"""Independent examples from CPF Board rate tables and QA reproductions."""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from horilla.testkit import make_company, make_employee
from employee.singapore_models import SingaporeEmployeeDetails
from payroll.cpf import contribution_amounts, contribution_rates, age_band
from payroll.models.models import Contract, Allowance, Deduction, Payslip
from payroll.views.component_views import payroll_calculation


class CpfTableTests(SimpleTestCase):
    def test_low_wage_boundaries_and_whole_dollar_rounding(self):
        for wage, expected in [(0,(0,0)),(50,(0,0)),(50.01,(0,9)),(500,(0,85)),
                               (501,(0,86)),(600,(60,102)),(750,(150,128)),
                               (750.01,(150,128)),(4001,(800,680)),(3818.18,(763,650))]:
            with self.subTest(wage=wage):
                self.assertEqual(contribution_amounts(wage, 0, Decimal('.2'), Decimal('.17')), expected)

    def test_birthday_band_switches_after_birthday_month(self):
        for age, previous_band, next_band in [(55,0,1),(60,1,2),(65,2,3),(70,3,4)]:
            for day in [1,15,28]:
                dob = date(2026-age,9,day)
                with self.subTest(age=age, day=day):
                    self.assertEqual(age_band(dob,date(2026,9,1)),previous_band)
                    self.assertEqual(age_band(dob,date(2026,10,1)),next_band)

    def test_rates_use_payroll_year_and_pr_anniversary_month(self):
        dob=date(1990,1,1)
        for month, expected in [(date(2026,5,1),1),(date(2026,6,1),2),
                                (date(2027,5,1),2),(date(2027,6,1),3)]:
            self.assertEqual(contribution_rates(month,dob,'pr',date(2025,5,15))[2],expected)
        for year, expected in [(2025,(Decimal('.17'),Decimal('.155'))),
                               (2026,(Decimal('.18'),Decimal('.16'))),
                               (2027,(Decimal('.19'),Decimal('.165')))]:
            self.assertEqual(contribution_rates(date(year,9,1),date(1969,1,1),'citizen')[:2],expected)

    def test_all_graduated_age_bands_and_approved_higher_pr_schemes(self):
        expected={1:[(5,4),(5,4),(5,3.5),(5,3.5),(5,3.5)],
                  2:[(15,9),(12.5,6),(7.5,3.5),(5,3.5),(5,3.5)]}
        for pr_year in [1,2]:
            for i,age in enumerate([30,57,62,67,72]):
                values=contribution_rates(date(2026,9,1),date(2026-age,1,1),'pr',date(2027-pr_year,5,15))[:2]
                self.assertEqual(values,tuple(Decimal(str(v))/100 for v in expected[pr_year][i]))
        with self.assertRaisesMessage(ValidationError,'approval'):
            contribution_rates(date(2026,9,1),date(1990,1,1),'pr',date(2026,5,15),'full_both')
        self.assertEqual(contribution_rates(date(2026,9,1),date(1990,1,1),'pr',date(2026,5,15),'full_employer','approval',date(2026,1,1))[:2],(Decimal('.05'),Decimal('.17')))
        self.assertEqual(contribution_rates(date(2026,9,1),date(1990,1,1),'pr',date(2026,5,15),'full_both','approval',date(2026,1,1))[:2],(Decimal('.20'),Decimal('.17')))
        self.assertEqual(contribution_rates(date(2026,9,1),date(1990,1,1),'pr',date(2026,5,15),'full_both','approval',date(2026,10,1))[:2],(Decimal('.05'),Decimal('.04')))


class CpfPayrollIntegrationTests(TestCase):
    def setUp(self):
        self.employee=make_employee(company=make_company('CPF QA'),email='cpf-qa@test.example')
        self.employee.dob=date(1990,1,1);self.employee.save()
        work=self.employee.employee_work_info;work.date_joining=date(2025,1,1);work.save()
        Contract.objects.filter(employee_id=self.employee).delete()
        self.contract=Contract.objects.create(employee_id=self.employee,contract_name='CPF QA',
            contract_start_date=date(2025,1,1),contract_status='active',wage=4000,
            wage_type='monthly',payroll_workweek='five_day',deduct_leave_from_basic_pay=True,
            calculate_daily_leave_amount=True)
        self.details=SingaporeEmployeeDetails.objects.create(employee=self.employee,residency_status='citizen')

    def salary(self,start=date(2026,9,1),end=date(2026,9,30)):
        with patch('payroll.views.component_views.get_pending_attendance',return_value=[]):
            return payroll_calculation(self.employee,start,end)

    def allowance(self,amount=200,**kwargs):
        item=Allowance.objects.create(title='Cash component',amount=amount,is_fixed=True,**kwargs)
        item.specific_employees.add(self.employee)
        return item

    def test_ordinary_cash_and_reimbursement_are_separate_from_taxability(self):
        self.allowance(is_taxable=False)
        self.allowance(100,cpf_wage_type='excluded')
        data=self.salary();self.assertEqual(data['gross_pay'],4300)
        self.assertEqual(data['statutory_cpf']['employee_amount'],840)
        self.assertEqual(data['statutory_cpf']['employer_amount'],714)
        self.assertEqual(Payslip(gross_pay=data['gross_pay'],pay_head_data=data).sdl_display,10.5)

    def test_legacy_static_cpf_is_replaced_once_and_custom_deduction_retained(self):
        for kind,amount in [('cpf',123),('none',10)]:
            d=Deduction.objects.create(title=kind,statutory_type=kind,is_fixed=True,amount=amount,is_pretax=False)
            d.specific_employees.add(self.employee)
        data=self.salary();self.assertEqual(data['total_deductions'],810)
        self.assertEqual(sum(d.get('statutory_type')=='cpf' for d in data['post_tax_deductions']),1)

    def test_foreigner_and_explicit_exemption_no_cpf(self):
        self.details.residency_status='foreigner';self.details.save()
        self.assertIsNone(self.salary()['statutory_cpf'])
        self.details.residency_status='citizen';self.details.save()
        self.contract.cpf_exempt=True;self.contract.cpf_exemption_reason='Approved exemption reference';self.contract.save()
        self.assertIsNone(self.salary()['statutory_cpf'])

    def test_missing_birth_date_is_actionable(self):
        self.employee.dob=None;self.employee.save()
        with self.assertRaisesMessage(ValidationError,'date of birth'):self.salary()

    def test_snapshot_records_applied_scheme_before_approved_effective_month(self):
        self.details.residency_status='pr';self.details.pr_effective_date=date(2026,5,15);self.details.save()
        self.contract.cpf_pr_scheme='full_both';self.contract.cpf_pr_approval='QA approved scheme'
        self.contract.cpf_pr_scheme_start=date(2026,10,1);self.contract.save()
        before=self.salary()['statutory_cpf']
        self.assertEqual(before['scheme'],'graduated')
        self.assertEqual(before['configured_pr_scheme'],'full_both')
        self.assertEqual(before['employee_amount'],200)
        after=self.salary(date(2026,10,1),date(2026,10,31))['statutory_cpf']
        self.assertEqual(after['scheme'],'full_both')
        self.assertEqual(after['employee_amount'],800)

    def test_ow_ceiling_historical_and_current(self):
        self.contract.wage=9000;self.contract.save()
        for year,expected in [(2025,(1480,1258)),(2026,(1600,1360))]:
            data=self.salary(date(year,9,1),date(year,9,30))['statutory_cpf']
            self.assertEqual((data['employee_amount'],data['employer_amount']),expected)

    def test_aw_uses_separate_annual_cap_and_requires_current_estimate(self):
        import calendar
        for month in range(1,9):
            Payslip.objects.create(employee_id=self.employee,start_date=date(2026,month,1),
                end_date=date(2026,month,calendar.monthrange(2026,month)[1]),status="confirmed",
                pay_head_data={"statutory_cpf":{"ow":8000,"ow_subject":8000,"aw":0,"aw_subject":0,
                    "employee_rate":0.2,"employer_rate":0.17,"employee_amount":1600,"employer_amount":1360}})
        self.contract.wage=8000;self.contract.save()
        self.allowance(20000,cpf_wage_type='aw',one_time_date=date(2026,9,20))
        with self.assertRaisesMessage(ValidationError,'estimated annual OW'):self.salary()
        self.contract.cpf_estimate_year=2026;self.contract.cpf_annual_ow_estimate=96000;self.contract.save()
        data=self.salary()['statutory_cpf'];self.assertEqual(data['aw_subject'],6000)
        self.assertEqual((data['employee_amount'],data['employer_amount']),(2800,2380))

    def test_pr_conversion_uses_only_post_conversion_earned_wages(self):
        self.details.residency_status='pr';self.details.pr_effective_date=date(2026,9,7);self.details.save()
        data=self.salary()['statutory_cpf'];self.assertEqual(data['ow'],3272.73)
        self.assertEqual((data['employee_amount'],data['employer_amount']),(163,132))

    def test_monthly_consolidation_prevents_double_ceiling(self):
        Payslip.objects.create(employee_id=self.employee,start_date=date(2026,9,1),end_date=date(2026,9,15),pay_head_data={})
        with self.assertRaisesMessage(ValidationError,'Consolidate'):self.salary()

    def test_fixed_allowance_prorates_but_reimbursement_and_oneoff_do_not(self):
        work=self.employee.employee_work_info;work.date_joining=date(2026,9,7);work.save()
        self.allowance(220)
        self.allowance(100,cpf_wage_type='excluded')
        self.allowance(50,one_time_date=date(2026,9,10))
        data=self.salary();self.assertEqual([a['amount'] for a in data['allowances']],[180,100,50])
        self.assertAlmostEqual(data['gross_pay'],4000*18/22+330)

    def test_expired_contract_still_computes_historical_salary(self):
        self.contract.contract_end_date=date(2026,9,18);self.contract.save()
        self.assertEqual(self.contract.contract_status,'expired')
        self.assertAlmostEqual(self.salary()['basic_pay'],4000*14/22)

    def record_month(self,month):
        import calendar,json
        from payroll.methods.methods import save_payslip
        data=self.salary(date(2026,month,1),date(2026,month,calendar.monthrange(2026,month)[1]))
        return save_payslip(employee=self.employee,start_date=data['start_date'],end_date=data['end_date'],
            status='confirmed',basic_pay=data['basic_pay'],contract_wage=data['contract_wage'],
            gross_pay=data['gross_pay'],deduction=data['total_deductions'],net_pay=data['net_pay'],
            pay_data=json.loads(data['json_data']),installments=data['installments'])

    def test_final_month_aw_shortfall_is_added_once_without_rewriting_prior_slips(self):
        self.contract.cpf_estimate_year=2026;self.contract.cpf_annual_ow_estimate=48000;self.contract.save()
        self.allowance(60000,cpf_wage_type='aw',one_time_date=date(2026,1,20))
        earlier=[self.record_month(month) for month in range(1,6)]
        original=[s.pay_head_data for s in earlier]
        self.contract.contract_end_date=date(2026,6,30);self.contract.save()
        data=self.salary(date(2026,6,1),date(2026,6,30))['statutory_cpf']
        self.assertEqual(data['aw_employee_adjustment'],1200)
        self.assertEqual(data['aw_employer_adjustment'],1020)
        self.assertEqual((data['employee_amount'],data['employer_amount']),(2000,1700))
        self.assertTrue(data['aw_reconciliation'])
        current=self.record_month(6)
        self.assertEqual(current.pay_head_data['statutory_cpf'],data)
        self.assertEqual(self.salary(date(2026,6,1),date(2026,6,30))['statutory_cpf'],data)
        for slip,expected in zip(earlier,original):
            slip.refresh_from_db();self.assertEqual(slip.pay_head_data,expected)

    def test_aw_refund_requires_reconciliation_instead_of_negative_deduction(self):
        self.contract.cpf_estimate_year=2026;self.contract.cpf_annual_ow_estimate=48000;self.contract.save()
        self.allowance(60000,cpf_wage_type='aw',one_time_date=date(2026,1,20))
        for month in range(1,6):self.record_month(month)
        self.contract.cpf_annual_ow_estimate=80000;self.contract.save()
        with self.assertRaisesMessage(ValidationError,'excess CPF'):
            self.salary(date(2026,6,1),date(2026,6,30))

    def test_aw_missing_earlier_months_does_not_assume_empty_ledger(self):
        self.allowance(5000,cpf_wage_type='aw',one_time_date=date(2026,9,20))
        self.contract.cpf_estimate_year=2026;self.contract.cpf_annual_ow_estimate=48000;self.contract.save()
        with self.assertRaisesMessage(ValidationError,'earlier employment months'):self.salary()

    def test_ambiguous_contract_period_is_rejected(self):
        Contract.objects.create(employee_id=self.employee,contract_name='Old overlapping',
            contract_start_date=date(2026,8,1),contract_end_date=date(2026,9,15),
            contract_status='expired',wage=3000,payroll_workweek='five_day')
        with self.assertRaisesMessage(ValidationError,'Multiple contracts'):self.salary()

    def test_singapore_company_requires_residency_without_legacy_cpf_component(self):
        self.details.delete()
        company=self.employee.employee_work_info.company_id
        company.country="Singapore";company.save()
        with self.assertRaisesMessage(ValidationError,'residency status'):self.salary()
