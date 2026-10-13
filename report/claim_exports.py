"""One shared claim selection for the register and its original-receipt bundle."""

import csv
import hashlib
import io
import re
import zipfile
from datetime import datetime, time, timedelta

from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone

from base.auth_backends import (
    get_allowed_company_ids,
    get_effective_permission_codenames,
)
from report.engine import apply_org_filters


def claim_queryset(filters):
    from payroll.models.models import Reimbursement

    qs = Reimbursement.objects.all()
    if filters.claim_date_basis == "payroll":
        qs = qs.filter(allowance_on__range=(filters.from_date, filters.to_date))
    else:
        start = timezone.make_aware(datetime.combine(filters.from_date, time.min))
        end = timezone.make_aware(
            datetime.combine(filters.to_date + timedelta(days=1), time.min)
        )
        qs = qs.filter(
            Q(created_at__isnull=True) | Q(created_at__gte=start, created_at__lt=end)
        )
    if filters.claim_status:
        qs = qs.filter(status=filters.claim_status)
    if filters.claim_type:
        qs = qs.filter(type=filters.claim_type)
    request = filters.request
    if request and not request.user.is_superuser:
        allowed = [
            pk
            for pk in get_allowed_company_ids(request.user)
            if set(get_effective_permission_codenames(request.user, pk))
            & {"view_reimbursement", "view_payslip"}
        ]
        qs = qs.filter(employee_id__employee_work_info__company_id__in=allowed)
    return apply_org_filters(
        qs,
        filters,
        prefix="employee_id__employee_work_info",
        employee_prefix="employee_id",
    )


def attachment_fields(claim):
    files = ([claim.attachment] if claim.attachment else []) + [
        a.attachment for a in claim.other_attachments.all() if a.attachment
    ]
    seen = set()
    for field in files:
        if field.name not in seen:
            seen.add(field.name)
            yield field


def can_export_claims(request, definition, filters):
    from base.models import DefaultExportPermission
    from report.access import user_can_export_report

    company_ids = (
        claim_queryset(filters)
        .order_by()
        .values_list("employee_id__employee_work_info__company_id", flat=True)
        .distinct()
    )
    for company_id in company_ids:
        policy = DefaultExportPermission.objects.filter(
            company_id_id=company_id
        ).first()
        if (
            not request.user.is_superuser
            and policy
            and not policy.is_enabled
            and "export_reimbursement"
            not in get_effective_permission_codenames(request.user, company_id)
        ):
            return False
        if not user_can_export_report(
            request.user, definition, request=request, company_id=company_id
        ):
            return False
    return True


class BundleTooLarge(ValueError):
    pass


def export_claim_bundle(payload, claims, meta):
    from report.export import export_xlsx

    output = io.BytesIO()
    manifest = []
    total_size = 0
    max_size = 100 * 1024 * 1024
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for claim in claims:
            seen_hashes = set()
            fields = list(attachment_fields(claim))
            if not fields:
                manifest.append([claim.pk, "", "no attachments", ""])
            for index, field in enumerate(fields, 1):
                original = field.name.replace("\\", "/").rsplit("/", 1)[-1]
                safe_name = (
                    re.sub(r"[^\w.\- ]", "_", original).strip(". ")[:160] or "receipt"
                )
                filename = f"receipts/claim-{claim.pk}/{index:02d}-{safe_name}"
                try:
                    with field.open("rb") as source:
                        data = source.read(max_size - total_size + 1)
                    total_size += len(data)
                    if total_size > max_size:
                        raise BundleTooLarge(
                            "Receipt bundle exceeds 100 MB. Choose a shorter period or export individual employees."
                        )
                    digest = hashlib.sha256(data).hexdigest()
                    if digest in seen_hashes:
                        manifest.append([claim.pk, original, "duplicate omitted", ""])
                        continue
                    seen_hashes.add(digest)
                    archive.writestr(filename, data)
                    manifest.append([claim.pk, original, "included", filename])
                except BundleTooLarge:
                    raise
                except Exception:
                    manifest.append(
                        [claim.pk, original, "MISSING — unable to read attachment", ""]
                    )
        partial = any(row[2].startswith("MISSING") for row in manifest)
        workbook = export_xlsx(payload, filename="claims.xlsx", meta=meta)
        archive.writestr("claims.xlsx", workbook.content)
        manifest_output = io.StringIO()
        from report.export import _neutralize_formula

        writer = csv.writer(manifest_output)
        writer.writerow(["Claim ID", "Original filename", "Result", "ZIP path"])
        writer.writerows(
            [[_neutralize_formula(str(value)) for value in row] for row in manifest]
        )
        archive.writestr(
            "attachment-manifest.csv", manifest_output.getvalue().encode("utf-8-sig")
        )
        archive.writestr(
            "README.txt",
            (
                "PARTIAL EXPORT: Some attachments could not be read. Check attachment-manifest.csv.\n"
                if partial
                else "Complete export of selected claims and available attachment records.\n"
            )
            + "claims.xlsx contains the matching claim details. Original receipts are grouped by claim ID. Duplicate file content is included once per claim. No attachments means none were recorded; it is not evidence that receipts were checked.\n",
        )
    response = HttpResponse(output.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = (
        'attachment; filename="claims' + ("-PARTIAL" if partial else "") + '.zip"'
    )
    response["X-Export-Partial"] = "1" if partial else "0"
    return response
