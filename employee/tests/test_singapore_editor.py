"""Employee editor permissions, versioned saves and verified zero-fund declarations."""
from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import Group, Permission
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, TestCase, override_settings

from base.models import CompanyGroupAssignment
from employee.models import Employee
from employee.singapore_editor import editor_context
from employee.singapore_models import SingaporeContributionProfile, SingaporeDetailsAudit, SingaporeEmployeeDetails
from employee.views import employee_view_update
from horilla.testkit import make_company, make_employee


class SingaporeEditorTests(TestCase):
    def setUp(self):
        self.company = make_company("SG Editor", country="Singapore")
        self.hr = make_employee(company=self.company, email="sg-editor-hr@test.example")
        self.employee = make_employee(company=self.company, email="sg-editor@test.example")
        self.grant("change_employee")

    def grant(self, *codenames):
        user = self.hr.employee_user_id
        user.user_permissions.add(*Permission.objects.filter(codename__in=codenames))
        for key in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
            user.__dict__.pop(key, None)

    def request(self, method="get", data=None, query="?tab=singapore&salary_month=2026-09-01", htmx=False):
        request = getattr(RequestFactory(), method)(f"/employee/employee-view-update/{self.employee.pk}/{query}", data or {})
        request.user = self.hr.employee_user_id
        request.session = SessionStore()
        request.session["selected_company"] = "all"
        request.session.create()
        request._messages = FallbackStorage(request)
        if htmx:
            request.META["HTTP_HX_REQUEST"] = "true"
        return request

    def declaration(self, **changes):
        data = {"form": "singapore_contributions", "salary_month": "2026-09-01",
            "shg-effective_month": "2026-09-01", "shg-primary_race": "other",
            "shg-muslim_status": "no", "shg-residency_status": "foreigner",
            "shg-work_pass_type": "S_PASS", "shg-declaration_reference": "Verified employee declaration",
            "shg-revision": ""}
        data.update({f"shg-{fund}_mode": "auto" for fund in ("cdac", "ecf", "sinda", "mbmf")})
        data.update(changes)
        return data

    def test_general_employee_edit_cannot_leak_restricted_data_or_save_it(self):
        SingaporeEmployeeDetails.objects.create(employee=self.employee, identity_type="FIN", identity_number="F1234567D", residency_status="foreigner")
        context = editor_context(self.request(), self.employee)
        self.assertTrue(context["show_singapore_tab"])
        self.assertFalse(context["can_view_singapore_details"])
        self.assertNotIn("singapore_details", context)
        with self.assertRaises(PermissionDenied):
            editor_context(self.request("post", self.declaration()), self.employee)
        self.assertFalse(SingaporeContributionProfile.objects.exists())
        self.assertFalse(SingaporeDetailsAudit.objects.exists())

    def test_view_only_has_masked_details_and_no_edit_forms(self):
        self.grant("view_singaporeemployeedetails")
        SingaporeEmployeeDetails.objects.create(employee=self.employee, identity_type="FIN", identity_number="F1234567D", residency_status="foreigner")
        response = employee_view_update(self.request(), self.employee.pk)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("•••••567D", html)
        self.assertNotIn("F1234567D", html)
        self.assertNotIn('name="sg-identity_number"', html)
        self.assertNotIn('name="shg-primary_race"', html)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(set(SingaporeDetailsAudit.objects.values_list("action", flat=True)), {"view_masked", "view_contribution"})

    def test_full_page_and_htmx_fragment_embed_both_forms_and_preserve_tab(self):
        self.grant("view_singaporeemployeedetails", "change_singaporeemployeedetails")
        for htmx in (False, True):
            response = employee_view_update(self.request(htmx=htmx), self.employee.pk)
            self.assertEqual(response.status_code, 200)
            html = response.content.decode()
            self.assertIn('id="step-singapore"', html)
            self.assertIn('name="sg-identity_number"', html)
            self.assertIn('name="shg-primary_race"', html)
            self.assertIn('name="shg-effective_month"', html)
            self.assertIn('"singapore"', html)
            self.assertIn("no-store", response["Cache-Control"])

    def test_foreign_non_muslim_zero_funds_saves_and_displays_ready(self):
        self.grant("view_singaporeemployeedetails", "change_singaporeemployeedetails")
        context = editor_context(self.request("post", self.declaration()), self.employee)
        profile = SingaporeContributionProfile.objects.get(employee=self.employee)
        self.assertEqual(profile.created_by, self.hr.employee_user_id)
        self.assertEqual(context["contribution_profile"], profile)
        self.assertEqual(context["contribution_funds"], [])
        self.assertEqual(context["contribution_form"].initial["revision"], str(profile.pk))
        self.assertEqual(SingaporeDetailsAudit.objects.get().action, "update_contribution")
        response = employee_view_update(self.request(), self.employee.pk)
        self.assertIn("No mandatory self-help group contribution applies", response.content.decode())

    def test_unknown_muslim_status_blocks_save_even_for_foreign_employee(self):
        self.grant("view_singaporeemployeedetails", "change_singaporeemployeedetails")
        context = editor_context(self.request("post", self.declaration(**{"shg-muslim_status": ""})), self.employee)
        self.assertIn("muslim_status", context["contribution_form"].errors)
        self.assertFalse(SingaporeContributionProfile.objects.exists())

    def test_stale_declaration_rejected_and_future_version_does_not_cover_past(self):
        self.grant("view_singaporeemployeedetails", "change_singaporeemployeedetails")
        context = editor_context(self.request("post", self.declaration(**{"shg-effective_month": "2026-10-01"})), self.employee)
        self.assertIsNone(context["contribution_profile"])
        self.assertIsNotNone(context["contribution_latest"])
        context = editor_context(self.request("post", self.declaration()), self.employee)
        self.assertIn("changed while", str(context["contribution_form"].non_field_errors()))
        self.assertEqual(SingaporeContributionProfile.objects.count(), 1)
        self.assertEqual(SingaporeContributionProfile.objects.get().effective_month, date(2026, 10, 1))

    def test_employment_save_is_separate_and_stale_revision_does_not_overwrite(self):
        self.grant("view_singaporeemployeedetails", "change_singaporeemployeedetails")
        data = {"form": "singapore_details", "sg-revision": "", "sg-residency_status": "foreigner", "sg-work_pass_type": "S_PASS"}
        editor_context(self.request("post", data), self.employee)
        record = SingaporeEmployeeDetails.objects.get(employee=self.employee)
        self.assertEqual(record.residency_status, "foreigner")
        self.assertFalse(SingaporeContributionProfile.objects.exists())
        data["sg-work_pass_type"] = "EP"
        context = editor_context(self.request("post", data), self.employee)
        self.assertIn("changed while", str(context["singapore_details_form"].non_field_errors()))
        record.refresh_from_db()
        self.assertEqual(record.work_pass_type, "S_PASS")

    @override_settings(COMPANY_SCOPED_PERMISSIONS=True)
    def test_permission_from_another_company_cannot_edit_this_employee(self):
        group = Group.objects.create(name="SG restricted editor test")
        group.permissions.add(*Permission.objects.filter(codename__in=("view_singaporeemployeedetails", "change_singaporeemployeedetails")))
        CompanyGroupAssignment.objects.create(user=self.hr.employee_user_id, company=make_company("Other editor company"), group=group)
        with self.assertRaises(PermissionDenied):
            editor_context(self.request("post", self.declaration()), self.employee)
        self.assertFalse(SingaporeContributionProfile.objects.exists())

    def test_new_effective_version_preserves_prior_declaration(self):
        self.grant("view_singaporeemployeedetails", "change_singaporeemployeedetails")
        editor_context(self.request("post", self.declaration()), self.employee)
        original = SingaporeContributionProfile.objects.get()
        editor_context(self.request("post", self.declaration(**{"shg-revision": str(original.pk), "shg-effective_month": "2026-10-01", "shg-muslim_status": "yes"})), self.employee)
        original.refresh_from_db()
        self.assertEqual(original.muslim_status, "no")
        self.assertEqual(SingaporeContributionProfile.objects.count(), 2)
        self.assertEqual(editor_context(self.request(), self.employee)["contribution_funds"], [])
