from django.contrib.sessions.backends.db import SessionStore
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase
from django.utils.datastructures import MultiValueDict

from horilla.horilla_middlewares import _thread_locals
from horilla.testkit import clear_selected_company, make_company, make_employee
from payroll.forms.component_forms import MultipleFileField, ReimbursementForm
from payroll.models.models import Reimbursement, ReimbursementMultipleAttachment


class ReimbursementReceiptTests(TestCase):
    def setUp(self):
        clear_selected_company()
        self.employee = make_employee(
            company=make_company("Receipt QA"), email="zeyu+receipt-qa@neutron.sg"
        )
        self.request = RequestFactory().post("/")
        self.request.session = SessionStore()
        self.request.session["selected_company"] = str(
            self.employee.employee_work_info.company_id_id
        )
        self.request.user = self.employee.employee_user_id
        self.request.user.is_superuser = True
        _thread_locals.request = self.request
        self.data = {
            "employee_id": str(self.employee.pk),
            "type": "reimbursement",
            "title": "Receipt QA",
            "description": "Synthetic receipt test",
            "allowance_on": "2026-10-14",
            "amount": "12.34",
        }

    def tearDown(self):
        _thread_locals.request = None
        clear_selected_company()
        super().tearDown()

    def form(self, files=None, instance=None, **overrides):
        return ReimbursementForm(
            dict(self.data, **overrides), files or MultiValueDict(), instance=instance
        )

    def claim(self, attachment=None):
        return Reimbursement.objects.create(
            employee_id=self.employee,
            type="reimbursement",
            title="Existing QA",
            description="QA",
            allowance_on="2026-10-14",
            amount=12.34,
            attachment=attachment,
        )

    def test_empty_multiple_upload_runs_required_validation(self):
        for data in ([], (), None):
            with self.subTest(data=data), self.assertRaises(ValidationError):
                MultipleFileField().clean(data)

    def test_new_reimbursement_without_receipt_is_rejected(self):
        form = self.form()
        self.assertFalse(form.is_valid())
        self.assertIn("attachment", form.errors)
        self.assertIn("receipt", str(form.errors["attachment"]))
        self.assertEqual(Reimbursement.objects.count(), 0)

    def test_employee_self_service_also_rejects_missing_receipt(self):
        self.request.user.is_superuser = False
        form = self.form()
        self.assertNotIn("employee_id", form.fields)
        self.assertFalse(form.is_valid())
        self.assertIn("attachment", form.errors)

    def test_valid_receipts_are_accepted_and_all_files_are_validated(self):
        uploads = MultiValueDict(
            {
                "attachment": [
                    SimpleUploadedFile("receipt.pdf", b"%PDF-QA"),
                    SimpleUploadedFile("receipt2.pdf", b"%PDF-QA-2"),
                ]
            }
        )
        form = self.form(uploads)
        self.assertTrue(form.is_valid(), form.errors)
        uploads = MultiValueDict(
            {
                "attachment": [
                    SimpleUploadedFile("good.pdf", b"%PDF-QA"),
                    SimpleUploadedFile("empty.pdf", b""),
                ]
            }
        )
        form = self.form(uploads)
        self.assertFalse(form.is_valid())
        self.assertIn("attachment", form.errors)

    def test_edit_with_existing_primary_receipt_needs_no_reupload(self):
        claim = self.claim("private/receipt.pdf")
        form = self.form(instance=claim)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.instance.attachment.name, "private/receipt.pdf")

    def test_edit_with_existing_secondary_receipt_needs_no_reupload(self):
        claim = self.claim()
        claim.other_attachments.add(
            ReimbursementMultipleAttachment.objects.create(
                attachment="private/secondary.pdf"
            )
        )
        form = self.form(instance=claim)
        self.assertTrue(form.is_valid(), form.errors)

    def test_legacy_claim_without_any_receipt_requires_one_on_edit(self):
        form = self.form(instance=self.claim())
        self.assertFalse(form.is_valid())
        self.assertIn("attachment", form.errors)

    def test_cannot_clear_the_only_receipt(self):
        form = self.form(
            instance=self.claim("private/receipt.pdf"), **{"attachment-clear": "on"}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("attachment", form.errors)

    def test_encashment_does_not_require_receipt(self):
        # Encashment has separate eligibility checks; do not add a receipt
        # requirement to either non-expense transaction type.
        for kind in ("bonus_encashment", "leave_encashment"):
            form = self.form(
                type=kind, bonus_to_encash="1", ad_to_encash="1", cfd_to_encash="0"
            )
            form.is_valid()
            self.assertNotIn("attachment", form.fields)
            self.assertNotIn("attachment", form.errors)

    def test_api_validation_rejects_missing_or_cleared_receipt(self):
        from horilla_api.api_serializers.payroll.serializers import (
            ReimbursementSerializer,
        )
        from rest_framework.exceptions import ValidationError as ApiValidationError

        for instance in (None, self.claim("private/receipt.pdf")):
            serializer = ReimbursementSerializer(instance=instance)
            with self.assertRaises(ApiValidationError) as caught:
                serializer.validate(
                    {
                        "employee_id": self.employee,
                        "type": "reimbursement",
                        "attachment": None,
                    }
                )
            self.assertIn("attachment", caught.exception.detail)

    def test_api_edit_accepts_retained_receipt(self):
        from horilla_api.api_serializers.payroll.serializers import (
            ReimbursementSerializer,
        )

        serializer = ReimbursementSerializer(instance=self.claim("private/receipt.pdf"))
        self.assertEqual(serializer.validate({}), {})
