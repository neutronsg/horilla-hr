"""Validate each shared upload before writing any storage objects."""

from pathlib import Path
from zipfile import BadZipFile, ZipFile

import pymupdf
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from PIL import Image


OFFICE_TYPES = {
    ".docx": (
        "word/document.xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    ".xlsx": (
        "xl/workbook.xml",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    ".pptx": (
        "ppt/presentation.xml",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ),
}


def validate_document_file(upload):
    limit = getattr(settings, "COMPANY_DOCUMENT_MAX_FILE_SIZE", 20 * 1024 * 1024)
    if not upload.size or upload.size > limit:
        raise ValidationError(
            _("Each file must be non-empty and no larger than %(size)s MB."),
            params={"size": limit // (1024 * 1024)},
        )
    extension = Path(upload.name).suffix.lower()
    try:
        upload.seek(0)
        if extension == ".pdf":
            if not upload.read(5) == b"%PDF-":
                raise ValueError
            upload.seek(0)
            with pymupdf.open(stream=upload.read(), filetype="pdf") as pdf:
                if pdf.needs_pass or not pdf.page_count:
                    raise ValueError
            content_type = "application/pdf"
        elif extension in (".jpg", ".jpeg", ".png"):
            image = Image.open(upload)
            expected = "PNG" if extension == ".png" else "JPEG"
            if image.format != expected:
                raise ValueError
            image.verify()
            content_type = "image/png" if expected == "PNG" else "image/jpeg"
        elif extension in OFFICE_TYPES:
            required_part, content_type = OFFICE_TYPES[extension]
            with ZipFile(upload) as archive:
                names = archive.namelist()
                if required_part not in names or "[Content_Types].xml" not in names:
                    raise ValueError
                if any("vbaproject" in name.lower() for name in names):
                    raise ValueError
                # Inspect a bounded manifest, not an arbitrarily large ZIP member.
                info = archive.getinfo("[Content_Types].xml")
                if (
                    info.file_size > 1024 * 1024
                    or b"macroenabled" in archive.read(info).lower()
                ):
                    raise ValueError
        else:
            raise ValidationError(_("Upload PDF, JPEG, PNG, DOCX, XLSX or PPTX files."))
    except (
        ValueError,
        OSError,
        SyntaxError,
        EOFError,
        BadZipFile,
        Image.DecompressionBombError,
        KeyError,
        pymupdf.FileDataError,
    ):
        raise ValidationError(
            _("The file contents do not match a supported document type.")
        )
    finally:
        upload.seek(0)
    upload.verified_content_type = content_type
    return upload
