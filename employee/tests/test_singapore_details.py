from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import Group, Permission
from django.contrib.sessions.backends.db import SessionStore
from django.core.exceptions import ValidationError
from django.db import connection
from django.http import HttpResponse
from django.template import Context, Engine
from django.test import RequestFactory, TestCase, override_settings

from base.methods import has_export_access
from employee.forms import EmployeeForm
from employee.models import Employee
from employee.singapore import SingaporeDetailsForm, can_access_singapore_details, singapore_details
from employee.singapore_models import SingaporeDetailsAudit, SingaporeEmployeeDetails
from employee.views import about_tab
from horilla.testkit import make_company, make_employee


class SingaporeDetailsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        company = make_company("Singapore tests")
        cls.hr = make_employee(company=company, email="hr@sg.test")
        cls.employee = make_employee(company=company, email="staff@sg.test")
        cls.other = make_employee(company=make_company("Other SG"), email="other@sg.test")

    def request(self, method="get", data=None, query="", user=None):
        req = getattr(RequestFactory(), method)("/employee/singapore-details/1/" + query, data or {})
        req.user = user or self.hr.employee_user_id
        req.session = {}
        return req

    def grant(self, *codenames):
        user = self.hr.employee_user_id
        user.user_permissions.add(*Permission.objects.filter(codename__in=codenames))
        for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
            user.__dict__.pop(attr, None)

    def details(self):
        return SingaporeEmployeeDetails.objects.create(
            employee=self.employee, identity_type="NRIC", identity_number="S1234567D",
            residency_status="pr", pr_effective_date=date(2020, 1, 15),
        )

    def about_request(self):
        request = RequestFactory().get("/employee/about-tab/1/", HTTP_HX_REQUEST="true")
        request.user = self.hr.employee_user_id
        request.session = SessionStore()
        request.session.create()
        return request

    def test_about_tab_shows_masked_singapore_details_and_personal_email(self):
        self.grant("view_employee", "view_singaporeemployeedetails")
        record = self.details()
        record.personal_email = "private@sg.test"
        record.save(update_fields=["personal_email"])

        response = about_tab(self.about_request(), self.employee.pk)
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("Singapore Employment", html)
        self.assertIn("Personal email", html)
        self.assertIn("private@sg.test", html)
        self.assertIn(record.masked_identity_number, html)
        self.assertNotIn(record.identity_number, html)
        self.assertNotIn("Edit details", html)
        self.assertEqual(SingaporeDetailsAudit.objects.get().action, "view_masked")

    def test_about_tab_hides_restricted_details_without_permission(self):
        self.grant("view_employee")
        record = self.details()
        record.personal_email = "private@sg.test"
        record.save(update_fields=["personal_email"])

        response = about_tab(self.about_request(), self.employee.pk)
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Singapore Employment", html)
        self.assertNotIn("Personal email", html)
        self.assertNotIn("private@sg.test", html)
        self.assertNotIn(record.masked_identity_number, html)
        self.assertFalse(SingaporeDetailsAudit.objects.exists())

    def test_ordinary_employee_and_manager_permissions_do_not_grant_access(self):
        self.grant("view_employee", "change_employee")
        self.assertFalse(can_access_singapore_details(self.request(), self.employee))
        self.assertEqual(singapore_details(self.request(), self.employee.pk).status_code, 403)
        self.assertEqual(singapore_details(self.request(user=self.employee.employee_user_id), self.employee.pk).status_code, 403)

    def test_migration_default_groups_do_not_auto_grant_private_permissions(self):
        from base.signals import _DEFAULT_HRMS_GROUPS, _resolve_group_permissions, _sync_export_permissions
        for name, config in _DEFAULT_HRMS_GROUPS.items():
            self.assertFalse(
                _resolve_group_permissions(config).filter(content_type__model__in=[
                    "singaporeemployeedetails", "singaporedetailsaudit",
                ]).exists(), name
            )
        Permission.objects.filter(codename__in=["export_singaporeemployeedetails", "export_singaporedetailsaudit"]).delete()
        _sync_export_permissions()
        self.assertFalse(Permission.objects.filter(codename="export_singaporeemployeedetails").exists())

    def test_company_boundary_and_separate_edit_permission(self):
        self.grant("view_singaporeemployeedetails")
        self.assertTrue(can_access_singapore_details(self.request(), self.employee))
        self.assertFalse(can_access_singapore_details(self.request(), self.other))
        self.assertEqual(singapore_details(self.request(query="?edit=1"), self.employee.pk).status_code, 403)
        self.assertEqual(singapore_details(self.request("post"), self.employee.pk).status_code, 403)

    @override_settings(COMPANY_SCOPED_PERMISSIONS=True)
    def test_role_in_one_company_cannot_reveal_details_in_another_allowed_company(self):
        from base.models import CompanyGroupAssignment
        hr_group = Group.objects.create(name="SG HR restricted test")
        hr_group.permissions.add(Permission.objects.get(codename="view_singaporeemployeedetails"))
        staff_group = Group.objects.create(name="SG basic test")
        user = self.hr.employee_user_id
        CompanyGroupAssignment.objects.create(user=user, group=hr_group, company_id=self.employee.employee_work_info.company_id_id)
        CompanyGroupAssignment.objects.create(user=user, group=staff_group, company_id=self.other.employee_work_info.company_id_id)
        self.assertTrue(can_access_singapore_details(self.request(), self.employee))
        self.assertFalse(can_access_singapore_details(self.request(), self.other))

    def test_identifiers_are_encrypted_at_rest_and_support_key_rotation(self):
        with override_settings(SECRET_KEY="old-hr-key", SECRET_KEY_FALLBACKS=[]):
            record = self.details()
            with connection.cursor() as cur:
                cur.execute("SELECT identity_number FROM employee_singaporeemployeedetails WHERE id=%s", [record.pk])
                encrypted = cur.fetchone()[0]
            self.assertNotIn("S1234567D", encrypted)
        with override_settings(SECRET_KEY="new-hr-key", SECRET_KEY_FALLBACKS=["old-hr-key"]):
            self.assertEqual(SingaporeEmployeeDetails.objects.get(pk=record.pk).identity_number, "S1234567D")

    def test_read_view_masks_identifiers_and_logs_no_values(self):
        self.grant("view_singaporeemployeedetails")
        self.details()
        captured = {}
        def render(request, template, context):
            captured.update(context)
            return HttpResponse("ok")
        with patch("employee.singapore.render", side_effect=render):
            response = singapore_details(self.request(), self.employee.pk)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIsNone(captured["form"])
        # Render the real template: an authorised read must not send plaintext in HTML.
        engine = Engine(
            dirs=[str(Path(__file__).parents[1] / "templates")],
            loaders=[("django.template.loaders.locmem.Loader", {"index.html": "{% block content %}{% endblock %}"}), "django.template.loaders.filesystem.Loader"],
            libraries={"i18n": "django.templatetags.i18n"},
        )
        html = engine.get_template("employee/singapore/details.html").render(Context(captured))
        self.assertNotIn("S1234567D", html)
        self.assertIn("4567D"[-4:], html)
        event = SingaporeDetailsAudit.objects.get()
        self.assertEqual(event.action, "view_masked")
        self.assertEqual(event.fields, [])

    def test_invalid_identity_and_pr_combination(self):
        record = SingaporeEmployeeDetails(employee=self.employee, identity_type="FIN", identity_number="S1234567D")
        with self.assertRaises(ValidationError): record.full_clean()
        record.identity_type = "NRIC"
        record.pr_effective_date = date(2020, 1, 1)
        record.residency_status = "citizen"
        with self.assertRaises(ValidationError): record.full_clean()

    def test_blanks_allowed_and_date_widget_preserves_dates(self):
        form = SingaporeDetailsForm({})
        self.assertTrue(form.is_valid(), form.errors)
        form = SingaporeDetailsForm(instance=self.details())
        self.assertIn('value="2020-01-15"', str(form["pr_effective_date"]))

    def test_update_is_audited_without_values_and_stale_revision_rejected(self):
        self.grant("view_singaporeemployeedetails", "change_singaporeemployeedetails")
        record = self.details()
        data = {"identity_type": "NRIC", "identity_number": "S7654321B", "residency_status": "citizen", "revision": record.updated_at.isoformat()}
        with patch("employee.singapore.messages.success"):
            response = singapore_details(self.request("post", data), self.employee.pk)
        self.assertEqual(response.status_code, 302)
        event = SingaporeDetailsAudit.objects.get()
        self.assertIn("identity_number", event.fields)
        self.assertNotIn("S7654321B", str(event.fields))
        with patch("employee.singapore.render", return_value=HttpResponse("stale")) as render:
            singapore_details(self.request("post", data), self.employee.pk)
        self.assertIn("changed while", str(render.call_args.args[2]["form"].non_field_errors()))
        self.assertEqual(SingaporeDetailsAudit.objects.count(), 1)

    def test_generic_exports_and_employee_form_cannot_expose_private_fields(self):
        self.assertFalse(has_export_access(self.request(), SingaporeEmployeeDetails))
        user = self.hr.employee_user_id
        user.is_superuser = True
        self.assertFalse(has_export_access(self.request(user=user), SingaporeEmployeeDetails))
        self.assertNotIn("identity_number", EmployeeForm().fields)
        self.assertNotIn("singaporeemployeedetails", [f.name for f in Employee._meta.get_fields()])

    def test_generic_export_endpoint_rejects_restricted_model(self):
        from horilla_views.views import export_data
        req = self.request("post", {"ids": "[]", "columns": "[]"})
        req.GET = {"model": "employee.SingaporeEmployeeDetails"}
        self.assertEqual(export_data(req).status_code, 403)

    def test_authorised_full_view_is_audited(self):
        self.grant("view_singaporeemployeedetails", "change_singaporeemployeedetails")
        self.details()
        with patch("employee.singapore.render", return_value=HttpResponse("ok")) as render:
            singapore_details(self.request(query="?edit=1"), self.employee.pk)
        self.assertEqual(render.call_args.args[2]["form"]["identity_number"].value(), "S1234567D")
        self.assertEqual(SingaporeDetailsAudit.objects.get().action, "view_full")

    def test_full_emergency_name_and_preferred_name_do_not_change_legal_name(self):
        self.employee.emergency_contact_name = "Fuji Afriani (Krystal Loh)"
        self.employee.preferred_name = "Everyday Name"
        legal_name = self.employee.get_full_name()
        self.employee.save()
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.emergency_contact_name, "Fuji Afriani (Krystal Loh)")
        self.assertEqual(self.employee.get_display_name(), "Everyday Name")
        self.assertEqual(self.employee.get_full_name(), legal_name)
