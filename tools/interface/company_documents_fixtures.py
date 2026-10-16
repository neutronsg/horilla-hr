"""Opt-in synthetic shared documents for the local browser preview."""

from io import BytesIO

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from reportlab.pdfgen import canvas

from attendance.models import AttendanceGeneralSetting
from base.models import CompanyGroupAssignment
from employee.company_document_files import validate_document_file
from employee.models import Employee, Policy, PolicyMultipleFile
from horilla.testkit import clear_selected_company


def seed_company_documents(company):
    clear_selected_company()
    AttendanceGeneralSetting.objects.update_or_create(
        company_id=company, defaults={"enable_check_in": False}
    )
    hr = Employee.objects.get(email="zeyu+ui-2@neutron.sg")
    CompanyGroupAssignment.objects.get_or_create(
        user=hr.employee_user_id,
        company=company,
        group=Group.objects.get(name="HR Manager"),
    )
    manual_id = None
    for title, category, published, pinned in (
        ("Your insurance guide", "insurance", True, True),
        ("Employee handbook", "policies", True, False),
        ("Expense claim form", "guides", True, False),
        ("Benefits guide for HR review", "insurance", False, False),
    ):
        document = (
            Policy.objects.entire().filter(company_id=company, title=title).first()
        )
        if document is None:
            document = Policy.objects.entire().create(
                title=title,
                body="A practical guide for employees. Contact HR if you need help finding the right information.",
                category=category,
                is_visible_to_all=published,
                pinned=pinned,
                published_at=timezone.now() if published else None,
            )
            document.company_id.add(company)
            buffer = BytesIO()
            pdf = canvas.Canvas(buffer)
            pdf.setFont("Helvetica-Bold", 22)
            pdf.drawString(50, 750, title)
            pdf.setFont("Helvetica", 12)
            pdf.drawString(
                50, 710, "Synthetic demonstration document for local testing."
            )
            pdf.save()
            upload = validate_document_file(
                SimpleUploadedFile(title + ".pdf", buffer.getvalue())
            )
            file = PolicyMultipleFile.objects.create(
                attachment=upload,
                original_name=upload.name,
                size=upload.size,
                content_type=upload.verified_content_type,
            )
            document.attachments.add(file)
        if document.pinned != pinned:
            document.pinned = pinned
            document.save(update_fields=["pinned"])
        if category == "insurance" and published:
            manual_id = document.pk
    return manual_id
