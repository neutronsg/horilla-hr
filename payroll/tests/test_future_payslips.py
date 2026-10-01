"""Future pay periods can be prepared as draft payslips."""

import json
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.http import QueryDict
from django.test import TestCase, override_settings
from django.urls import reverse

from horilla.testkit import make_company, make_employee
from payroll.forms.component_forms import GeneratePayslipForm
from payroll.models.models import Contract, Payslip


@override_settings(SIMPLE_HISTORY_ENABLED=False)
class FuturePayslipDateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        company = make_company("Future Payroll")
        cls.employee = make_employee(company=company, email="future@payroll.test")
        Contract.objects.filter(employee_id=cls.employee).delete()
        Contract.objects.create(
            contract_name="Active Monthly",
            employee_id=cls.employee,
            contract_start_date=date.today() - timedelta(days=30),
            wage_type="monthly",
            wage=3000,
            contract_status="active",
        )
        cls.hr = make_employee(company=company, email="future-hr@payroll.test")
        cls.user = cls.hr.employee_user_id
        cls.user.is_new_employee = False
        cls.user.save(update_fields=["is_new_employee"])
        cls.user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="payroll", codename="add_payslip"
            )
        )

    def form_data(self, start, end):
        data = QueryDict(mutable=True)
        data.setlist("employee_id", [str(self.employee.pk)])
        data["start_date"] = start.isoformat()
        data["end_date"] = end.isoformat()
        return data

    def test_batch_form_allows_future_end_and_future_period(self):
        today = date.today()
        for start, end in (
            (today.replace(day=1), today + timedelta(days=1)),
            (today + timedelta(days=1), today + timedelta(days=30)),
        ):
            with self.subTest(start=start, end=end):
                form = GeneratePayslipForm(data=self.form_data(start, end))
                self.assertTrue(form.is_valid(), form.errors)

    def test_batch_form_still_rejects_reversed_dates(self):
        today = date.today()
        form = GeneratePayslipForm(
            data=self.form_data(
                today + timedelta(days=2), today + timedelta(days=1)
            )
        )
        self.assertFalse(form.is_valid())
        self.assertIn("end_date", form.errors)

    def test_ajax_validation_allows_future_end(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("validate-start-date"),
            {
                "start_date": date.today().isoformat(),
                "end_date": (date.today() + timedelta(days=1)).isoformat(),
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"valid": True, "errors": []})

    def test_future_batch_saves_draft_without_employee_notification(self):
        start = date.today().replace(day=1)
        end = date.today() + timedelta(days=1)
        calculated = {
            "start_date": start,
            "end_date": end,
            "contract_wage": 3000,
            "basic_pay": 3000,
            "gross_pay": 3000,
            "total_deductions": 0,
            "net_pay": 3000,
            "json_data": json.dumps({"start_date": str(start), "end_date": str(end)}),
            "installments": [],
        }
        self.client.force_login(self.user)
        with (
            patch("horilla.settings.PAYROLL_USE_ATTENDANCE", True),
            patch(
                "attendance.views.summary.build_monthly_summary",
                return_value=([{"employee": self.employee}], 1, {}),
            ) as summary,
            patch(
                "payroll.views.component_views.payroll_calculation",
                return_value=calculated,
            ),
            patch("payroll.views.component_views.calculate_employer_contribution"),
            patch("payroll.views.component_views.notify.send") as notify,
        ):
            response = self.client.post(
                reverse("generate-payslip"), self.form_data(start, end)
            )

        self.assertEqual(response.status_code, 302)
        slip = Payslip.objects.get(employee_id=self.employee, start_date=start, end_date=end)
        self.assertEqual(slip.status, "draft")
        self.assertEqual(summary.call_args.kwargs["assume_future_present"], True)
        notify.assert_not_called()

    def test_batch_does_not_reuse_another_employees_joining_date(self):
        start, end = date(2030, 1, 1), date(2030, 1, 31)
        self.employee.employee_first_name = "A Midmonth"
        self.employee.save()
        Contract.objects.filter(employee_id=self.employee).update(contract_start_date=date(2030, 1, 15))
        other = make_employee(company=self.employee.employee_work_info.company_id, email="full-month@payroll.test", first_name="Z Fullmonth")
        Contract.objects.filter(employee_id=other).delete()
        Contract.objects.create(contract_name="Full month", employee_id=other, contract_start_date=start, contract_status="active", wage=3000)
        data = self.form_data(start, end)
        data.setlist("employee_id", [str(self.employee.pk), str(other.pk)])
        def calculate(employee, first, last, **kwargs):
            return {"start_date": first, "end_date": last, "contract_wage": 3000,
                    "basic_pay": 3000, "gross_pay": 3000, "net_pay": 3000, "total_deductions": 0,
                    "json_data": json.dumps({"start_date": str(first), "end_date": str(last)}), "installments": []}
        self.client.force_login(self.user)
        with patch("horilla.settings.PAYROLL_USE_ATTENDANCE", False), patch("payroll.views.component_views.payroll_calculation", side_effect=calculate) as calculation, patch("payroll.views.component_views.calculate_employer_contribution"):
            response = self.client.post(reverse("generate-payslip"), {key: data.getlist(key) if key == "employee_id" else data[key] for key in data})
        self.assertEqual(response.status_code, 302)
        starts = {call.args[0].pk: call.args[1] for call in calculation.call_args_list}
        self.assertEqual(len(starts), 2, (response.url, [str(m) for m in response.wsgi_request._messages], list(Contract.objects.values("employee_id", "contract_status", "contract_start_date"))))
        self.assertEqual(starts[self.employee.pk], date(2030, 1, 15))
        self.assertEqual(starts[other.pk], start)
