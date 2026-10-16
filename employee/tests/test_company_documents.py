"""Shared publishing, tenant boundaries, file lifecycle and legacy entry points."""

from importlib import import_module
from io import BytesIO
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from auditlog.models import LogEntry
from django.apps import apps
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from reportlab.pdfgen import canvas
from rest_framework.test import APIClient

from base.models import CompanyGroupAssignment
from employee.company_document_access import (
    can_manage_document,
    employee_company_id,
    published_documents,
)
from employee.company_document_files import validate_document_file
from employee.models import Policy, PolicyMultipleFile
from horilla.horilla_middlewares import _thread_locals, set_selected_company
from horilla.testkit import make_company, make_employee


def pdf_upload(name="Insurance guide.pdf", text="Synthetic insurance manual"):
    stream = BytesIO()
    pdf = canvas.Canvas(stream)
    pdf.drawString(40, 750, text)
    pdf.save()
    return SimpleUploadedFile(name, stream.getvalue(), content_type="application/pdf")


@override_settings(
    COMPANY_SCOPED_PERMISSIONS=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class CompanyDocumentTests(TestCase):
    def setUp(self):
        set_selected_company(None)
        _thread_locals.request = None
        self.addCleanup(set_selected_company, None)
        self.addCleanup(setattr, _thread_locals, "request", None)
        self.media = TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=self.media.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.company = make_company("Shared Documents Co")
        self.other_company = make_company("Other Documents Co")
        self.employee = self.person(self.company, "reader")
        self.other = self.person(self.other_company, "other-reader")
        self.hr = self.person(self.company, "publisher")
        self.grant(self.hr, self.company)
        self.document = self.document_for(self.company)

    def person(self, company, name):
        employee = make_employee(company=company, email=f"{name}@documents.test")
        employee.employee_user_id.is_new_employee = False
        employee.employee_user_id.save(update_fields=["is_new_employee"])
        return employee

    def grant(
        self,
        employee,
        company,
        role="HR Manager",
        permissions=("view", "add", "change", "delete"),
    ):
        group, _ = Group.objects.get_or_create(name=role)
        group.permissions.set(
            Permission.objects.filter(
                content_type__app_label="employee",
                codename__in=[f"{p}_policy" for p in permissions],
            )
        )
        CompanyGroupAssignment.objects.get_or_create(
            user=employee.employee_user_id, company=company, group=group
        )
        employee.employee_user_id.groups.add(group)

    def document_for(
        self,
        company,
        title="Company insurance manual",
        *,
        visible=True,
        active=True,
        pinned=False,
    ):
        document = Policy.objects.entire().create(
            title=title,
            category="insurance",
            is_visible_to_all=visible,
            is_active=active,
            pinned=pinned,
        )
        if company:
            document.company_id.add(company)
        upload = validate_document_file(pdf_upload())
        file = PolicyMultipleFile.objects.create(
            attachment=upload,
            original_name=upload.name,
            size=upload.size,
            content_type=upload.verified_content_type,
        )
        document.attachments.add(file)
        return document

    def sign_in(self, employee, client=None):
        client = client or self.client
        client.force_login(employee.employee_user_id)
        session = client.session
        session["selected_company"] = "all"
        session.save()
        return client

    def file_url(self, document=None, file=None):
        document = document or self.document
        file = file or document.current_files[0]
        return reverse("company-document-file", args=[document.pk, file.pk])

    def edit_data(self, document=None, **changes):
        document = document or self.document
        document.refresh_from_db()
        data = {
            "title": document.title,
            "category": document.category,
            "body": document.body,
            "company": self.company.pk,
            "revision": document.updated_at.isoformat(),
            "action": "publish",
        }
        data.update(changes)
        return data

    def test_one_file_is_shared_with_current_employees_and_new_hires(self):
        for employee in (self.employee, self.person(self.company, "new-hire")):
            self.sign_in(employee)
            response = self.client.get(reverse("company-documents"))
            self.assertContains(response, self.document.title)
            response = self.client.get(self.file_url())
            self.assertEqual(response.status_code, 200)
            self.assertTrue(b"".join(response.streaming_content).startswith(b"%PDF-"))
            self.assertIn("private", response["Cache-Control"])
            self.assertIn("no-store", response["Cache-Control"])
            self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(PolicyMultipleFile.objects.count(), 1)

    def test_sidebar_htmx_navigation_receives_the_full_content_selector(self):
        self.sign_in(self.employee)
        response = self.client.get(reverse("company-documents"), HTTP_HX_REQUEST="true")
        self.assertContains(response, 'id="ohMainContent"')
        response = self.client.get(reverse("search-policies"), HTTP_HX_REQUEST="true")
        self.assertNotContains(response, 'id="ohMainContent"')

    def test_drafts_archives_and_other_company_are_denied_on_every_read_path(self):
        hidden = [
            self.document_for(self.company, "Draft guide", visible=False),
            self.document_for(self.company, "Archived guide", active=False),
            self.document_for(self.other_company, "Other guide"),
            self.document_for(None, "Unscoped legacy guide"),
        ]
        self.sign_in(self.employee)
        response = self.client.get(reverse("company-documents"), {"state": "all"})
        api = APIClient()
        api.force_authenticate(self.employee.employee_user_id)
        for document in hidden:
            self.assertNotContains(response, document.title)
            self.assertEqual(
                self.client.get(
                    reverse("company-document-detail", args=[document.pk])
                ).status_code,
                404,
            )
            self.assertEqual(self.client.get(self.file_url(document)).status_code, 404)
            self.assertEqual(
                self.client.get(
                    reverse("view-policy"), {"instance_id": document.pk}
                ).status_code,
                404,
            )
            self.assertEqual(
                self.client.get(
                    reverse("get-attachments-policy"), {"policy_id": document.pk}
                ).status_code,
                404,
            )
            self.assertEqual(
                api.get(reverse("api-policy-detail", args=[document.pk])).status_code,
                404,
            )
        listing = api.get(reverse("api-policy-list"))
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(
            [record["id"] for record in listing.data["results"]], [self.document.pk]
        )
        self.assertNotIn("specific_employees", listing.data["results"][0])

    def test_employee_has_no_management_and_old_mutations_cannot_delete_foreign_files(
        self,
    ):
        self.sign_in(self.employee)
        self.assertEqual(
            self.client.get(reverse("company-document-create")).status_code, 403
        )
        self.assertEqual(
            self.client.post(
                reverse("company-document-edit", args=[self.document.pk]),
                self.edit_data(),
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                reverse("remove-attachment-policy"), {"policy_id": self.document.pk}
            ).status_code,
            405,
        )
        self.assertEqual(
            self.client.get(
                reverse("delete-policies"), {"ids": self.document.pk}
            ).status_code,
            405,
        )
        self.sign_in(self.hr)
        other_document = self.document_for(self.other_company)
        foreign_file = other_document.current_files[0]
        response = self.client.post(
            reverse("remove-attachment-policy")
            + f"?policy_id={self.document.pk}&ids={foreign_file.pk}"
        )
        self.assertEqual(response.status_code, 302)
        foreign_file.refresh_from_db()
        self.assertTrue(foreign_file.is_active)
        data = self.edit_data(remove_files=[foreign_file.pk])
        response = self.client.post(
            reverse("company-document-edit", args=[self.document.pk]), data
        )
        self.assertContains(response, "Select a valid choice")

    def test_company_role_and_permission_cannot_be_borrowed_from_another_company(self):
        self.grant(self.hr, self.company, permissions=("view",))
        self.grant(self.hr, self.other_company, role="Admin")
        self.sign_in(self.hr)
        self.assertFalse(
            can_manage_document(self.hr.employee_user_id, self.document, "change")
        )
        self.assertEqual(
            self.client.post(
                reverse("company-document-edit", args=[self.document.pk]),
                self.edit_data(),
            ).status_code,
            403,
        )
        response = self.client.post(
            reverse("company-document-create"),
            {
                "title": "Wrong company",
                "category": "insurance",
                "company": self.company.pk,
                "action": "draft",
            },
        )
        self.assertContains(response, "Select a valid choice")
        self.assertFalse(Policy.objects.entire().filter(title="Wrong company").exists())

    def test_multi_company_document_is_read_only_unless_all_scopes_allow_change(self):
        self.document.company_id.add(self.other_company)
        self.sign_in(self.hr)
        self.assertEqual(
            self.client.get(
                reverse("company-document-detail", args=[self.document.pk])
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                reverse("company-document-edit", args=[self.document.pk])
            ).status_code,
            403,
        )
        self.grant(self.hr, self.other_company, role="Admin")
        self.assertEqual(
            self.client.get(
                reverse("company-document-edit", args=[self.document.pk])
            ).status_code,
            200,
        )

    def test_hr_can_save_draft_publish_and_upload_multiple_files(self):
        self.sign_in(self.hr)
        response = self.client.post(
            reverse("company-document-create"),
            {
                "title": "Benefits handbook",
                "category": "insurance",
                "company": self.company.pk,
                "action": "draft",
                "pinned": "on",
            },
        )
        document = Policy.objects.entire().get(title="Benefits handbook")
        self.assertRedirects(
            response,
            reverse("company-document-detail", args=[document.pk]),
            fetch_redirect_response=False,
        )
        self.assertFalse(document.is_visible_to_all)
        data = self.edit_data(
            document, files=[pdf_upload(), pdf_upload("Claim form.pdf")]
        )
        response = self.client.post(
            reverse("company-document-edit", args=[document.pk]), data
        )
        self.assertEqual(response.status_code, 302)
        document.refresh_from_db()
        self.assertTrue(document.is_visible_to_all)
        self.assertEqual(len(document.current_files), 2)
        event = LogEntry.objects.filter(
            object_pk=str(document.pk), additional_data__event="publish"
        ).latest("timestamp")
        self.assertEqual(event.actor_id, self.hr.employee_user_id_id)
        self.sign_in(self.employee)
        self.assertContains(
            self.client.get(reverse("company-documents")), document.title
        )

    def test_publish_requires_a_file_and_validates_every_upload(self):
        self.sign_in(self.hr)
        data = {
            "title": "Unpublished",
            "category": "other",
            "company": self.company.pk,
            "action": "publish",
        }
        self.assertContains(
            self.client.post(reverse("company-document-create"), data),
            "Add at least one file",
        )
        data["files"] = [
            pdf_upload(),
            SimpleUploadedFile("unsafe.pdf", b"<html>not a pdf</html>"),
        ]
        self.assertContains(
            self.client.post(reverse("company-document-create"), data),
            "contents do not match",
        )
        self.assertFalse(Policy.objects.entire().filter(title="Unpublished").exists())
        self.assertEqual(PolicyMultipleFile.objects.count(), 1)

    def test_replacement_preserves_hr_history_and_rejects_stale_saves(self):
        self.sign_in(self.hr)
        old_file = self.document.current_files[0]
        old_url = self.file_url(file=old_file)
        data = self.edit_data(
            files=[pdf_upload("New insurance guide.pdf")], replace_file=old_file.pk
        )
        old_revision = data["revision"]
        self.assertEqual(
            self.client.post(
                reverse("company-document-edit", args=[self.document.pk]), data
            ).status_code,
            302,
        )
        old_file.refresh_from_db()
        self.assertFalse(old_file.is_active)
        self.document.refresh_from_db()
        new_file = self.document.current_files[0]
        self.assertEqual(new_file.replaces_id, old_file.pk)
        self.assertEqual(self.client.get(old_url).status_code, 200)
        stale = self.edit_data(title="Stale update", revision=old_revision)
        self.assertContains(
            self.client.post(
                reverse("company-document-edit", args=[self.document.pk]), stale
            ),
            "changed while you were editing",
        )
        self.sign_in(self.employee)
        self.assertEqual(self.client.get(old_url).status_code, 404)
        self.assertEqual(self.client.get(self.file_url(file=new_file)).status_code, 200)

    def test_failed_storage_write_keeps_current_edition_and_cleans_partial_upload(self):
        self.sign_in(self.hr)
        field = PolicyMultipleFile._meta.get_field("attachment")
        real_save = field.storage.save
        calls = []

        def fail_second(name, content, **kwargs):
            if calls:
                raise OSError("Synthetic upload failure")
            stored = real_save(name, content, **kwargs)
            calls.append(stored)
            return stored

        data = self.edit_data(
            title="Should roll back",
            files=[pdf_upload("One.pdf"), pdf_upload("Two.pdf")],
        )
        with patch.object(field.storage, "save", side_effect=fail_second):
            response = self.client.post(
                reverse("company-document-edit", args=[self.document.pk]), data
            )
        self.assertContains(response, "current files are unchanged")
        self.document.refresh_from_db()
        self.assertEqual(self.document.title, "Company insurance manual")
        self.assertEqual(len(self.document.current_files), 1)
        self.assertFalse(field.storage.exists(calls[0]))

    def test_unpublish_and_archive_are_post_only_revision_checked_and_revoke_stale_links(
        self,
    ):
        self.sign_in(self.hr)
        url = reverse("company-document-transition", args=[self.document.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(
            self.client.post(
                url, {"action": "unpublish", "revision": "stale"}
            ).status_code,
            409,
        )
        self.document.refresh_from_db()
        self.assertEqual(
            self.client.post(
                url,
                {
                    "action": "unpublish",
                    "revision": self.document.updated_at.isoformat(),
                },
            ).status_code,
            302,
        )
        self.sign_in(self.employee)
        self.assertEqual(self.client.get(self.file_url()).status_code, 404)
        self.sign_in(self.hr)
        self.document.refresh_from_db()
        self.assertEqual(
            self.client.post(
                url,
                {"action": "archive", "revision": self.document.updated_at.isoformat()},
            ).status_code,
            302,
        )
        self.document.refresh_from_db()
        self.assertFalse(self.document.is_active)
        self.assertTrue(
            self.document.current_files[0].attachment.storage.exists(
                self.document.current_files[0].attachment.name
            )
        )

    def test_csrf_is_required_for_writes(self):
        client = self.sign_in(self.hr, Client(enforce_csrf_checks=True))
        response = client.post(
            reverse("company-document-edit", args=[self.document.pk]), self.edit_data()
        )
        self.assertEqual(response.status_code, 403)

    def test_existing_hr_roles_keep_policy_permissions_while_generic_exports_are_blocked(
        self,
    ):
        from base.methods import has_export_access
        from base.signals import _DEFAULT_HRMS_GROUPS, _resolve_group_permissions

        for role in ("HR Manager", "Admin"):
            permissions = _resolve_group_permissions(_DEFAULT_HRMS_GROUPS[role])
            self.assertTrue(permissions.filter(codename="add_policy").exists())
            self.assertTrue(permissions.filter(codename="change_policy").exists())
        request = RequestFactory().get("/")
        request.user = self.hr.employee_user_id
        request.session = {}
        self.assertFalse(has_export_access(request, Policy))

    def test_dashboard_is_personal_and_pinned_first_independent_of_selected_company(
        self,
    ):
        self.document.pinned = True
        self.document.save()
        for i in range(4):
            self.document_for(self.company, f"Shared handbook {i}")
        foreign = self.document_for(
            self.other_company, "Foreign secret guide", pinned=True
        )
        self.grant(self.hr, self.other_company, role="Admin")
        self.sign_in(self.hr)
        session = self.client.session
        session["selected_company"] = str(self.other_company.pk)
        session.save()
        response = self.client.get(
            reverse("ess-dashboard"), {"from_date": "2000-01-01"}
        )
        self.assertEqual(response.status_code, 200)
        docs = list(response.context["company_documents"])
        self.assertEqual(len(docs), 3)
        self.assertEqual(docs[0].pk, self.document.pk)
        self.assertNotIn(foreign.pk, [doc.pk for doc in docs])
        self.assertContains(response, "Company documents")

    def test_lost_membership_and_inactive_employee_or_account_cannot_read(self):
        user = self.employee.employee_user_id
        self.assertEqual(published_documents(user).count(), 1)
        self.employee.employee_work_info.company_id = None
        self.employee.employee_work_info.save()
        self.assertIsNone(employee_company_id(user))
        self.employee.employee_work_info.company_id = self.company
        self.employee.employee_work_info.save()
        self.employee.is_active = False
        user._state.fields_cache["employee_get"] = self.employee
        self.assertIsNone(employee_company_id(user))
        user.is_active = False
        self.assertIsNone(employee_company_id(user))

    def test_legacy_migration_preserves_scoped_articles_and_hides_unscoped_rows(self):
        article = Policy.objects.entire().create(
            title="Existing handbook", body="Existing terms", is_visible_to_all=True
        )
        article.company_id.add(self.company)
        unscoped = Policy.objects.entire().create(
            title="Needs audience", is_visible_to_all=True
        )
        migration = import_module(
            "employee.migrations.0015_policy_category_policy_pinned_policy_published_at_and_more"
        )
        migration.prepare_shared_documents(apps, SimpleNamespace(connection=connection))
        article.refresh_from_db()
        unscoped.refresh_from_db()
        self.assertTrue(article.is_visible_to_all)
        self.assertIsNotNone(article.published_at)
        self.assertEqual(article.body, "Existing terms")
        self.assertFalse(unscoped.is_visible_to_all)
        self.sign_in(self.employee)
        self.assertContains(
            self.client.get(reverse("company-document-detail", args=[article.pk])),
            "Existing terms",
        )

    def test_api_writes_use_company_permissions_and_cannot_substitute_attachment_ids(
        self,
    ):
        api = APIClient()
        api.force_authenticate(self.employee.employee_user_id)
        self.assertEqual(
            api.post(reverse("api-policy-list"), {"title": "No"}).status_code, 403
        )
        api.force_authenticate(self.hr.employee_user_id)
        data = self.edit_data(attachments=[self.document.current_files[0].pk])
        self.assertEqual(
            api.put(
                reverse("api-policy-detail", args=[self.document.pk]),
                data,
                format="json",
            ).status_code,
            400,
        )
        data = self.edit_data(title="Updated through API")
        self.assertEqual(
            api.put(
                reverse("api-policy-detail", args=[self.document.pk]),
                data,
                format="json",
            ).status_code,
            200,
        )
        self.document.refresh_from_db()
        self.assertEqual(self.document.title, "Updated through API")

    def test_failed_new_upload_preserves_the_creation_form_without_a_phantom_record(
        self,
    ):
        self.sign_in(self.hr)
        storage = PolicyMultipleFile._meta.get_field("attachment").storage
        with patch.object(
            storage, "save", side_effect=OSError("Synthetic upload failure")
        ):
            response = self.client.post(
                reverse("company-document-create"),
                {
                    "title": "Retry this guide",
                    "category": "insurance",
                    "company": self.company.pk,
                    "action": "publish",
                    "files": [pdf_upload()],
                },
            )
        self.assertContains(response, "current files are unchanged")
        self.assertIsNone(response.context["document"].pk)
        self.assertContains(response, "Retry this guide")
        self.assertFalse(
            Policy.objects.entire().filter(title="Retry this guide").exists()
        )

    def test_jwt_file_download_uses_the_same_company_and_publication_boundary(self):
        from rest_framework_simplejwt.tokens import AccessToken

        api = APIClient()
        api.credentials(
            HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.employee.employee_user_id)}"
        )
        file = self.document.current_files[0]
        url = reverse("api-policy-file", args=[self.document.pk, file.pk])
        response = api.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(b"".join(response.streaming_content).startswith(b"%PDF-"))
        api.credentials(
            HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.other.employee_user_id)}"
        )
        self.assertEqual(api.get(url).status_code, 404)
        api.credentials(
            HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.employee.employee_user_id)}"
        )
        self.document.is_visible_to_all = False
        self.document.save()
        self.assertEqual(api.get(url).status_code, 404)

    @override_settings(COMPANY_DOCUMENT_MAX_FILE_SIZE=10)
    def test_upload_size_limit_is_enforced(self):
        with self.assertRaisesMessage(Exception, "no larger"):
            validate_document_file(pdf_upload())

    def test_office_macro_mismatch_and_fake_pdf_are_rejected(self):
        stream = BytesIO()
        with ZipFile(stream, "w") as archive:
            archive.writestr("[Content_Types].xml", "macroEnabled")
            archive.writestr("word/document.xml", "<document/>")
            archive.writestr("word/vbaProject.bin", "macro")
        for name, contents in (
            ("Guide.docx", stream.getvalue()),
            ("Fake.pdf", b"%PDF-1.4\nnot valid"),
            ("No.html", b"<html/>"),
        ):
            with self.subTest(name=name), self.assertRaises(Exception):
                validate_document_file(SimpleUploadedFile(name, contents))
