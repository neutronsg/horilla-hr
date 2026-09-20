"""Regression coverage for confirmed/paid employee payslip release."""

import json
from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from rest_framework.test import APIRequestFactory, force_authenticate

from base.ess_dashboard import ess_payslips
from horilla.testkit import make_company, make_employee
from horilla_api.api_views.payroll.views import (
    PayslipDownloadView,
    PayslipPDFAPIView,
    PayslipView,
)
from horilla_views.generic.cbv.views import HorillaListView
from payroll.access import can_view_payslip, visible_payslips
from payroll.cbv.payslip import PayrollTab, PayslipList
from payroll.models.models import Payslip
from payroll.models.tax_models import PayrollSettings
from payroll.views import component_views, views


# Access control tests do not exercise audit-history writes.
@override_settings(SIMPLE_HISTORY_ENABLED=False)
class PayslipAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        company = make_company("Payslip release")
        cls.employee = make_employee(company=company, email="owner@release.test")
        cls.other = make_employee(company=company, email="other@release.test")
        cls.hr = make_employee(company=company, email="hr@release.test")
        cls.user = cls.employee.employee_user_id
        cls.hr_user = cls.hr.employee_user_id
        cls.hr_user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="payroll", codename="view_payslip"
            )
        )
        PayrollSettings.objects.create(currency_symbol="S$")
        cls.slips = {}
        for month, status in enumerate(
            ("draft", "review_ongoing", "confirmed", "paid"), 1
        ):
            start, end = date(2025, month, 1), date(2025, month, 28)
            data = {"start_date": start.isoformat(), "end_date": end.isoformat()}
            for key in (
                "allowances",
                "basic_pay_deductions",
                "gross_pay_deductions",
                "pretax_deductions",
                "post_tax_deductions",
                "tax_deductions",
                "net_deductions",
            ):
                data[key] = []
            cls.slips[status] = Payslip.objects.create(
                employee_id=cls.employee,
                start_date=start,
                end_date=end,
                status=status,
                pay_head_data=data,
            )
        cls.other_slip = Payslip.objects.create(
            employee_id=cls.other,
            start_date=start,
            end_date=end,
            status="paid",
            pay_head_data=data,
        )

    def request(self, user=None, params=None):
        request = RequestFactory().get(
            "/payroll/payslip/", params or {}, HTTP_HX_REQUEST="true"
        )
        request.user = user or self.user
        request.session = {}
        return request

    def test_release_and_ownership_policy(self):
        for status, slip in self.slips.items():
            with self.subTest(status=status):
                self.assertEqual(
                    can_view_payslip(self.user, slip), status in ("confirmed", "paid")
                )
                self.assertTrue(can_view_payslip(self.hr_user, slip))
        self.assertFalse(can_view_payslip(self.user, self.other_slip))
        self.assertQuerySetEqual(
            visible_payslips(self.user, Payslip.objects.all()),
            [self.slips["confirmed"], self.slips["paid"]],
            ordered=False,
        )
        self.assertEqual(
            visible_payslips(self.hr_user, Payslip.objects.all()).count(), 5
        )

    def test_web_detail_and_download_reject_unreleased_and_other_employee(self):
        slips = [self.slips[s] for s in ("draft", "review_ongoing")]
        for view in (
            views.payslip_pdf,
            views.view_payslip_pdf,
            views.view_created_payslip,
        ):
            for slip in slips + [self.other_slip]:
                with self.subTest(
                    view=view.__name__, status=slip.status, owner=slip.employee_id_id
                ):
                    self.assertEqual(view(self.request(), slip.pk).status_code, 403)

    @patch(
        "payroll.views.views.generate_payslip_pdf", return_value=HttpResponse(b"PDF")
    )
    @patch("payroll.views.views.render", return_value=HttpResponse("preview"))
    def test_web_released_access_and_hr_preview(self, render, pdf):
        for user, slips in (
            (self.user, [self.slips["confirmed"], self.slips["paid"]]),
            (self.hr_user, self.slips.values()),
        ):
            for slip in slips:
                for view in (
                    views.payslip_pdf,
                    views.view_payslip_pdf,
                    views.view_created_payslip,
                ):
                    with self.subTest(
                        user=user.pk, status=slip.status, view=view.__name__
                    ):
                        self.assertEqual(
                            view(self.request(user), slip.pk).status_code, 200
                        )
        self.assertEqual(pdf.call_count, 6)
        self.assertEqual(render.call_count, 12)

    def test_api_details_and_downloads_reject_unreleased_and_other_employee(self):
        for view in (PayslipView, PayslipDownloadView, PayslipPDFAPIView):
            for slip in [self.slips[s] for s in ("draft", "review_ongoing")] + [
                self.other_slip
            ]:
                with self.subTest(view=view.__name__, slip=slip.pk):
                    self.assertEqual(
                        view().get(self.request(), slip.pk).status_code, 403
                    )

    @patch(
        "horilla_api.api_views.payroll.views.payslip_pdf",
        return_value=HttpResponse(b"PDF"),
    )
    @patch(
        "horilla_api.api_views.payroll.views.render_to_string", return_value="preview"
    )
    def test_api_released_access_and_hr_preview(self, render, pdf):
        for user, slips in (
            (self.user, [self.slips["confirmed"], self.slips["paid"]]),
            (self.hr_user, self.slips.values()),
        ):
            for slip in slips:
                for view in (PayslipView, PayslipDownloadView, PayslipPDFAPIView):
                    with self.subTest(
                        user=user.pk, status=slip.status, view=view.__name__
                    ):
                        self.assertEqual(
                            view().get(self.request(user), slip.pk).status_code, 200
                        )

    def test_list_and_profile_tab_preserve_release_and_ownership_scope(self):
        with patch.object(
            HorillaListView, "get_queryset", return_value=Payslip.objects.all()
        ):
            for view_class in (PayslipList, PayrollTab):
                view = object.__new__(view_class)
                view.request = self.request()
                view.kwargs = {"pk": self.employee.pk}
                self.assertQuerySetEqual(
                    view.get_queryset(),
                    [self.slips["confirmed"], self.slips["paid"]],
                    ordered=False,
                )
                if view_class is PayrollTab:
                    view.kwargs = {"pk": self.other.pk}
                    self.assertFalse(view.get_queryset().exists())
                view.request = self.request(self.hr_user)
                view.kwargs = {"pk": self.employee.pk}
                self.assertEqual(
                    view.get_queryset().count(), 4 if view_class is PayrollTab else 5
                )

    def test_select_all_and_filters_cannot_reveal_unreleased_ids(self):
        for view in (views.payslip_select, views.payslip_select_filter):
            response = view(self.request(params={"page": "all"}))
            self.assertCountEqual(
                json.loads(response.content)["payslip_ids"],
                [str(self.slips["confirmed"].pk), str(self.slips["paid"].pk)],
            )
        response = views.payslip_select_filter(
            self.request(
                params={
                    "page": "all",
                    "filter": json.dumps({"status": "review_ongoing"}),
                }
            )
        )
        self.assertEqual(json.loads(response.content)["payslip_ids"], [])

    @patch("payroll.methods.methods.get_pagination", new=lambda: 20)
    @patch("payroll.views.component_views.render", return_value=HttpResponse())
    def test_legacy_filter_cannot_override_release_or_owner(self, render):
        component_views.filter_payslip(
            self.request(params={"status": "review_ongoing"})
        )
        self.assertEqual(list(render.call_args.args[2]["payslips"]), [])
        component_views.filter_payslip(
            self.request(params={"employee_id": self.other.pk})
        )
        self.assertEqual(list(render.call_args.args[2]["payslips"]), [])
        component_views.filter_payslip(self.request())
        self.assertCountEqual(
            list(render.call_args.args[2]["payslips"]),
            [self.slips["confirmed"], self.slips["paid"]],
        )

    def test_ess_only_returns_released_payslips(self):
        response = ess_payslips(
            self.request(params={"from_date": "2025-01-01", "to_date": "2025-12-31"})
        )
        self.assertEqual(
            [p["id"] for p in json.loads(response.content)["payslips"]],
            [self.slips["paid"].pk, self.slips["confirmed"].pk],
        )

    def test_status_transition_releases_and_withdraws_employee_access(self):
        slip = self.slips["review_ongoing"]
        slip.status = "confirmed"
        slip.save(update_fields=["status"])
        self.assertTrue(
            visible_payslips(self.user, Payslip.objects.filter(pk=slip.pk)).exists()
        )
        slip.status = "review_ongoing"
        slip.save(update_fields=["status"])
        self.assertEqual(views.payslip_pdf(self.request(), slip.pk).status_code, 403)

    def test_api_list_cannot_override_release_or_owner(self):
        for params, expected in (
            ({}, [self.slips["paid"].pk, self.slips["confirmed"].pk]),
            ({"status": "confirmed"}, [self.slips["confirmed"].pk]),
            ({"status": "review_ongoing"}, []),
            ({"employee_id": self.other.pk}, []),
        ):
            request = APIRequestFactory().get("/api/payroll/payslip/", params)
            force_authenticate(request, user=self.user)
            response = PayslipView.as_view()(request)
            self.assertEqual(response.status_code, 200)
            self.assertCountEqual([p["id"] for p in response.data["results"]], expected)

    def test_dashboard_totals_exclude_unreleased_payslips(self):
        response = views.payslip_details(self.request(params={"period": "2025-02"}))
        self.assertEqual(json.loads(response.content)["no_of_emp"], 0)
        response = views.payslip_details(
            self.request(self.hr_user, {"period": "2025-02"})
        )
        self.assertEqual(json.loads(response.content)["no_of_emp"], 1)
