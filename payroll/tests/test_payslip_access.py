"""Regression coverage for confirmed/paid employee payslip release."""

import json
from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from rest_framework.test import APIRequestFactory, force_authenticate

from base.ess_dashboard import ess_payslips
from horilla.testkit import make_company, make_employee
from horilla.horilla_middlewares import _thread_locals, set_selected_company
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
from payroll.navigation import payslip_navigation, remember_payslip_order
from payroll.views import component_views, views


# Access control tests do not exercise audit-history writes.
@override_settings(SIMPLE_HISTORY_ENABLED=False)
class PayslipAccessTests(TestCase):
    def setUp(self):
        set_selected_company(None)
        _thread_locals.request = None
        self.addCleanup(set_selected_company, None)
        self.addCleanup(setattr, _thread_locals, "request", None)

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

    def test_navigation_preserves_filtered_list_order_and_disables_ends(self):
        self.hr_user.is_new_employee = False
        self.hr_user.save(update_fields=["is_new_employee"])
        later = Payslip.objects.create(
            employee_id=self.employee,
            start_date=date(2025, 6, 1),
            end_date=date(2025, 6, 28),
            status="confirmed",
            pay_head_data=self.slips["confirmed"].pay_head_data,
        )
        self.client.force_login(self.hr_user)
        response = self.client.get(
            reverse("payslip-list"),
            {"status": "confirmed", "filter_applied": "true", "sortby": "start_date"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200, dict(response.headers))
        import re

        token = re.search(
            r"navigation=([0-9a-f]{32})", response.content.decode()
        ).group(1)
        ordered = self.client.session["ordered_ids_payslip"]
        self.assertEqual(set(ordered), {str(later.pk), str(self.slips["confirmed"].pk)})
        for position, pk in enumerate(ordered):
            navigation = payslip_navigation(
                self.request(self.hr_user, {"navigation": token}),
                Payslip.objects.get(pk=pk),
            )
            self.assertEqual(navigation["payslip_count"], 2)
            self.assertEqual(navigation["payslip_position"], position + 1)
            self.assertEqual(navigation["previous_payslip_url"] is None, position == 0)
            self.assertEqual(navigation["next_payslip_url"] is None, position == 1)

        ids = [self.slips[s].pk for s in ("paid", "confirmed", "draft")]
        token = remember_payslip_order(self.request(self.hr_user), ids)
        for position, pk in enumerate(ids):
            navigation = payslip_navigation(
                self.request(self.hr_user, {"navigation": token}),
                Payslip.objects.get(pk=pk),
            )
            self.assertEqual(navigation["payslip_position"], position + 1)
            self.assertEqual(navigation["payslip_count"], 3)
            self.assertEqual(navigation["previous_payslip_url"] is None, position == 0)
            self.assertEqual(navigation["next_payslip_url"] is None, position == 2)
            if position < 2:
                self.assertIn(
                    reverse("view-created-payslip", args=[ids[position + 1]]),
                    navigation["next_payslip_url"],
                )

    def test_navigation_crafted_ids_are_filtered_for_employees(self):
        params = {
            "instance_ids": json.dumps(
                [
                    self.other_slip.pk,
                    self.slips["paid"].pk,
                    self.slips["draft"].pk,
                    self.slips["confirmed"].pk,
                    self.slips["paid"].pk,
                ]
            )
        }
        navigation = payslip_navigation(self.request(params=params), self.slips["paid"])
        self.assertEqual(navigation["payslip_count"], 2)
        self.assertEqual(navigation["payslip_position"], 1)
        self.assertIsNone(navigation["previous_payslip_url"])
        self.assertIn(
            reverse("view-created-payslip", args=[self.slips["confirmed"].pk]),
            navigation["next_payslip_url"],
        )
        response = views.view_created_payslip(
            self.request(params=params), self.other_slip.pk
        )
        self.assertEqual(response.status_code, 403)

    def test_navigation_rechecks_company_scope(self):
        other_company = make_company("Outside payroll scope")
        outsider = make_employee(company=other_company, email="outsider@release.test")
        outside = Payslip.objects.create(
            employee_id=outsider,
            start_date=date(2025, 4, 1),
            end_date=date(2025, 4, 28),
            status="paid",
            pay_head_data=self.slips["paid"].pay_head_data,
        )
        request = self.request(
            self.hr_user,
            {"instance_ids": json.dumps([outside.pk, self.slips["paid"].pk])},
        )
        request.session["selected_company"] = str(
            self.employee.employee_work_info.company_id_id
        )
        previous = getattr(_thread_locals, "request", None)
        _thread_locals.request = request
        set_selected_company(self.employee.employee_work_info.company_id_id)
        try:
            navigation = payslip_navigation(request, self.slips["paid"])
            self.assertEqual(navigation["payslip_count"], 1)
            self.assertIsNone(navigation["previous_payslip_url"])
            self.assertIsNone(navigation["next_payslip_url"])
        finally:
            _thread_locals.request = previous

    def test_navigation_cache_is_bound_to_user_and_access_is_rechecked(self):
        token = remember_payslip_order(
            self.request(self.hr_user), [self.other_slip.pk, self.slips["paid"].pk]
        )
        navigation = payslip_navigation(
            self.request(params={"navigation": token}), self.slips["paid"]
        )
        self.assertEqual(navigation["payslip_count"], 2)
        self.assertIsNone(navigation["previous_payslip_url"])
        token = remember_payslip_order(
            self.request(), [self.slips["paid"].pk, self.slips["confirmed"].pk]
        )
        Payslip.objects.filter(pk=self.slips["confirmed"].pk).update(status="draft")
        navigation = payslip_navigation(
            self.request(params={"navigation": token}), self.slips["paid"]
        )
        self.assertEqual(navigation["payslip_count"], 1)
        self.assertIsNone(navigation["next_payslip_url"])

    def test_navigation_without_list_context_uses_default_list_order(self):
        for params in (
            {},
            {"instance_ids": "broken"},
            {"instance_ids": "{}"},
            {"navigation": "expired"},
        ):
            navigation = payslip_navigation(
                self.request(params=params), self.slips["paid"]
            )
            self.assertEqual(navigation["payslip_position"], 1)
            self.assertEqual(navigation["payslip_count"], 2)
            self.assertIsNone(navigation["previous_payslip_url"])

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
