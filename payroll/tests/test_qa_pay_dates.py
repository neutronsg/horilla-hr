from datetime import date
from django.core.exceptions import ValidationError
from django.test import TestCase
from horilla.testkit import make_employee, make_company
from payroll.models.models import Payslip, Contract
from payroll.methods.methods import save_payslip

class PayslipPaymentDateTests(TestCase):
    def setUp(self):
        self.employee=make_employee(company=make_company('Payment QA'),email='qa-paydate@test.example')

    def slip(self,**kwargs):
        return Payslip.objects.create(employee_id=self.employee,start_date=date(2026,5,1),
            end_date=date(2026,5,31),pay_head_data={},**kwargs)

    def test_saturday_scheduled_sixth_is_not_moved_to_eighth(self):
        self.assertEqual(self.slip().payment_date,date(2026,6,6))
        self.assertEqual(Payslip.default_payment_date(date(2026,12,31)),date(2027,1,6))

    def test_manual_date_survives_updates_and_old_null_date_gets_default(self):
        slip=self.slip(payment_date=date(2026,6,5));slip.status='confirmed';slip.save(update_fields=['status'])
        slip.refresh_from_db();self.assertEqual(slip.payment_date,date(2026,6,5))
        Payslip.objects.filter(pk=slip.pk).update(payment_date=None)
        slip.refresh_from_db();slip.save(update_fields=['status']);slip.refresh_from_db()
        self.assertEqual(slip.payment_date,date(2026,6,6))

    def test_paid_payslip_cannot_be_overwritten_by_regeneration(self):
        slip=self.slip(status='paid',payment_date=date(2026,6,5))
        with self.assertRaisesMessage(ValidationError,'paid payslip'):
            save_payslip(employee=self.employee,start_date=slip.start_date,end_date=slip.end_date,status='draft')
        slip.refresh_from_db();self.assertEqual(slip.status,'paid')
        self.assertEqual(slip.payment_date,date(2026,6,5))

    def test_paid_regeneration_returns_form_error_instead_of_server_error(self):
        Contract.objects.filter(employee_id=self.employee).delete()
        Contract.objects.create(employee_id=self.employee,contract_name='Payment QA',
            contract_start_date=date(2026,1,1),contract_status='active',wage=4000,
            payroll_workweek='five_day',wage_type='monthly')
        user=self.employee.employee_user_id
        user.is_superuser=True;user.is_staff=True;user.is_new_employee=False;user.save()
        self.client.force_login(user,backend='base.auth_backends.CompanyScopedBackend')
        session=self.client.session
        session['selected_company']=str(self.employee.employee_work_info.company_id_id);session.save()
        slip=self.slip(status='paid',payment_date=date(2026,6,5))
        response=self.client.post('/payroll/create-payslip/',{'employee_id':self.employee.pk,
            'start_date':'2026-05-01','end_date':'2026-05-31','payment_date':'2026-06-06'},HTTP_HX_REQUEST='true')
        self.assertContains(response,'already exists')
        self.assertContains(response,'name="payment_date"')
        response=self.client.post('/payroll/generate-payslip/',{'employee_id':[self.employee.pk],
            'start_date':'2026-05-01','end_date':'2026-05-31'},HTTP_HX_REQUEST='true')
        self.assertEqual(response.status_code,302)
        slip.refresh_from_db();self.assertEqual(slip.status,'paid')
        self.assertEqual(slip.payment_date,date(2026,6,5))
