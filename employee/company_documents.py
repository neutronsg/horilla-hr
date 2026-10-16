"""Company document publishing and protected employee access."""

import logging
from pathlib import Path

from auditlog.models import LogEntry
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from base.models import Company
from employee.company_document_access import (
    can_manage_company,
    can_manage_document,
    can_read_document,
    employee_company_id,
    manageable_companies,
    visible_documents,
)
from employee.company_document_files import validate_document_file
from employee.models import Policy, PolicyMultipleFile

logger = logging.getLogger(__name__)


def document_breadcrumbs(document=None, *, editing=False):
    crumbs = [
        {
            "name": _("Neutron HR"),
            "url": reverse("home-page"),
            "found": True,
            "clickable": True,
        },
        {
            "name": _("Company documents"),
            "url": reverse("company-documents"),
            "found": True,
            "clickable": True,
        },
    ]
    if document is not None and document.pk:
        crumbs.append(
            {
                "name": document.title,
                "url": reverse("company-document-detail", args=[document.pk]),
                "found": True,
                "clickable": True,
                "record": True,  # keep the document title's own casing
            }
        )
    if editing:
        crumbs.append(
            {
                "name": _("Edit document") if document.pk else _("Add document"),
                "clickable": False,
            }
        )
    return crumbs


class MultipleDocumentInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleDocumentField(forms.FileField):
    widget = MultipleDocumentInput

    def clean(self, data, initial=None):
        if not data:
            return []
        files = data if isinstance(data, (list, tuple)) else [data]
        return [
            validate_document_file(super(MultipleDocumentField, self).clean(file))
            for file in files
        ]


class CompanyDocumentForm(forms.ModelForm):
    company = forms.ModelChoiceField(
        queryset=Company.objects.none(), label=_("Company")
    )
    files = MultipleDocumentField(
        label=_("Files"),
        required=False,
        help_text=_("PDF, JPEG, PNG, DOCX, XLSX or PPTX. Up to 20 MB per file."),
    )
    replace_file = forms.ModelChoiceField(
        queryset=PolicyMultipleFile.objects.none(),
        required=False,
        label=_("Replace an existing file"),
        empty_label=_("Add files without replacing"),
    )
    remove_files = forms.ModelMultipleChoiceField(
        queryset=PolicyMultipleFile.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label=_("Remove files"),
    )
    revision = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Policy
        fields = ("title", "category", "body", "pinned")
        labels = {"body": _("Description"), "pinned": _("Pin on employee dashboard")}
        widgets = {"body": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        existing = self.instance.pk is not None
        companies = list(self.instance.company_id.all()) if existing else []
        self.fields["company"].queryset = manageable_companies(user, "add")
        if companies:
            self.fields["company"].queryset = Company.objects.filter(
                pk__in=[c.pk for c in companies]
            )
            self.fields["company"].initial = companies[0].pk
            self.fields["company"].disabled = True
        else:
            home = employee_company_id(user)
            allowed = list(self.fields["company"].queryset.values_list("pk", flat=True))
            self.fields["company"].initial = (
                home if home in allowed else (allowed[0] if len(allowed) == 1 else None)
            )
        if existing:
            self.initial["revision"] = self.instance.updated_at.isoformat()
            files = self.instance.attachments.filter(is_active=True)
            self.fields["replace_file"].queryset = files
            self.fields["remove_files"].queryset = files
        for field in self.fields.values():
            if not isinstance(
                field.widget,
                (forms.CheckboxInput, forms.CheckboxSelectMultiple, forms.HiddenInput),
            ):
                field.widget.attrs["class"] = (
                    "oh-select cd-input"
                    if isinstance(field.widget, forms.Select)
                    else "oh-input cd-input"
                )
        self.fields["files"].widget.attrs[
            "accept"
        ] = ".pdf,.jpg,.jpeg,.png,.docx,.xlsx,.pptx"
        self.fields["replace_file"].label_from_instance = lambda file: file.display_name
        self.fields["remove_files"].label_from_instance = lambda file: file.display_name

    def clean(self):
        data = super().clean()
        if (
            self.instance.pk
            and data.get("revision") != self.instance.updated_at.isoformat()
        ):
            raise ValidationError(
                _("This document changed while you were editing. Reload before saving.")
            )
        replacement = data.get("replace_file")
        files = data.get("files", [])
        if replacement and len(files) != 1:
            self.add_error(
                "files", _("Choose exactly one new file when replacing an edition.")
            )
        removed = {file.pk for file in data.get("remove_files", [])}
        if replacement and replacement.pk in removed:
            self.add_error(
                "remove_files",
                _("A file cannot be removed and replaced in the same change."),
            )
        action = self.data.get("action")
        if action not in ("draft", "publish"):
            raise ValidationError(_("Choose Save draft or Publish."))
        if action == "publish":
            current = (
                {file.pk for file in self.instance.current_files}
                if self.instance.pk
                else set()
            )
            # Body-only legacy policies remain readable; new uploads need a file.
            legacy_article = self.instance.pk and bool(
                strip_tags(data.get("body", "")).strip()
            )
            if not files and not current.difference(removed) and not legacy_article:
                self.add_error("files", _("Add at least one file before publishing."))
        return data


def audit_document(document, user, action, **details):
    labels = {
        "publish": _("Published"),
        "save_draft": _("Draft saved"),
        "unpublish": _("Unpublished"),
        "archive": _("Archived"),
    }
    LogEntry.objects.log_create(
        document,
        actor=user,
        action=LogEntry.Action.UPDATE,
        changes={"company_documents": [None, action]},
        additional_data={
            "event": action,
            "label": str(labels.get(action, action)),
            **details,
        },
    )


def save_document(form, user):
    """Caller holds the parent lock. Storage cleanup accompanies DB rollback."""
    document = form.instance
    existing = bool(document.pk)
    if existing and not can_manage_document(user, document, "change"):
        raise PermissionDenied
    company = form.cleaned_data["company"]
    if not existing and not can_manage_company(user, company.pk, "add"):
        raise PermissionDenied
    written = []
    try:
        with transaction.atomic():
            document = form.save(commit=False)
            document.modified_by = user
            if not existing:
                document.created_by = user
            document.is_active = True
            document.is_visible_to_all = form.data.get("action") == "publish"
            if document.is_visible_to_all:
                document.published_at = timezone.now()
            document.save()
            if not document.company_id.exists():
                document.company_id.add(company)
            replacement = form.cleaned_data.get("replace_file")
            for upload in form.cleaned_data["files"]:
                file = PolicyMultipleFile(
                    original_name=Path(upload.name).name[:255],
                    size=upload.size,
                    content_type=upload.verified_content_type,
                    replaces=replacement,
                    created_by=user,
                    modified_by=user,
                )
                file.attachment.save(upload.name, upload, save=False)
                written.append((file.attachment.storage, file.attachment.name))
                file.save()
                document.attachments.add(file)
            retired = list(form.cleaned_data.get("remove_files", []))
            if replacement:
                retired.append(replacement)
            for file in retired:
                file.is_active = False
                file.modified_by = user
                file.save(update_fields=["is_active", "modified_by"])
            audit_document(
                document,
                user,
                "publish" if document.is_visible_to_all else "save_draft",
                fields=form.changed_data,
                replaced=replacement.pk if replacement else None,
                removed=[file.pk for file in retired],
            )
        return document
    except Exception:
        for storage, name in written:
            try:
                storage.delete(name)
            except Exception:
                logger.exception(
                    "Could not clean up an uncommitted company document upload"
                )
        if not existing:
            # A rolled-back insert still leaves a PK on the Python instance.
            # Keep the retry form in creation mode with valid cancel/navigation.
            document.pk = None
            document._state.adding = True
            document.is_visible_to_all = False
        raise


def _document(request, pk):
    document = get_object_or_404(visible_documents(request.user), pk=pk)
    if not can_read_document(request.user, document):
        raise Http404
    return document


@login_required
@never_cache
@require_http_methods(["GET"])
def library(request):
    documents = visible_documents(request.user)
    search = request.GET.get("search", "").strip()[:150]
    category = request.GET.get("category", "")
    state = request.GET.get("state", "published")
    if search:
        documents = documents.filter(
            Q(title__icontains=search) | Q(body__icontains=search)
        )
    if category:
        documents = documents.filter(category=category)
    if state == "draft":
        documents = documents.filter(is_active=True, is_visible_to_all=False)
    elif state == "archived":
        documents = documents.filter(is_active=False)
    elif state != "all":
        state = "published"
        documents = documents.filter(is_active=True, is_visible_to_all=True)
    page = Paginator(documents, 18).get_page(request.GET.get("page"))
    context = {
        "documents": page,
        "breadcrumbs": document_breadcrumbs(),
        "categories": Policy.CATEGORY_CHOICES,
        "search": search,
        "category": category,
        "state": state,
        "unscoped_count": (
            Policy.objects.entire().filter(company_id__isnull=True).count()
            if request.user.is_superuser
            else 0
        ),
        "can_add": manageable_companies(request.user, "add").exists(),
        "can_manage": manageable_companies(request.user).exists(),
    }
    for document in page:
        document.can_edit = can_manage_document(request.user, document, "change")
    # Sidebar HTMX navigation selects #ohMainContent out of a full page.
    # Only the retired search endpoint expects a records-only response.
    fragment = (
        request.headers.get("HX-Request")
        and getattr(request.resolver_match, "url_name", None) == "search-policies"
    )
    template = (
        "company_documents/records.html"
        if fragment
        else "company_documents/library.html"
    )
    return render(request, template, context)


@login_required
@never_cache
@require_http_methods(["GET"])
def detail(request, pk):
    document = _document(request, pk)
    manage = can_manage_document(request.user, document)
    history = (
        LogEntry.objects.filter(
            content_type=ContentType.objects.get_for_model(Policy), object_pk=str(pk)
        )
        .select_related("actor")
        .order_by("-timestamp")[:20]
        if manage
        else []
    )
    return render(
        request,
        "company_documents/detail.html",
        {
            "document": document,
            "breadcrumbs": document_breadcrumbs(document),
            "document_revision": document.updated_at.isoformat(),
            "can_edit": can_manage_document(request.user, document, "change"),
            "can_archive": can_manage_document(request.user, document, "delete"),
            "history": history,
            "previous_files": (
                [file for file in document.attachments.all() if not file.is_active]
                if manage
                else []
            ),
        },
    )


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def edit(request, pk=None):
    with transaction.atomic():
        document = _document(request, pk) if pk else Policy()
        if pk:
            document = Policy.objects.entire().select_for_update().get(pk=pk)
            if not can_manage_document(request.user, document, "change"):
                raise PermissionDenied
        elif not manageable_companies(request.user, "add").exists():
            raise PermissionDenied
        form = CompanyDocumentForm(
            request.POST if request.method == "POST" else None,
            request.FILES if request.method == "POST" else None,
            user=request.user,
            instance=document,
        )
        if request.method == "POST" and form.is_valid():
            try:
                document = save_document(form, request.user)
            except OSError:
                logger.exception("Company document upload failed")
                form.add_error(
                    "files",
                    _(
                        "The upload could not be saved. Your current files are unchanged; please try again."
                    ),
                )
            else:
                messages.success(
                    request,
                    (
                        _("Document published.")
                        if document.is_visible_to_all
                        else _("Draft saved.")
                    ),
                )
                return redirect("company-document-detail", pk=document.pk)
        return render(
            request,
            "company_documents/form.html",
            {
                "form": form,
                "document": document,
                "breadcrumbs": document_breadcrumbs(document, editing=True),
            },
        )


@login_required
@never_cache
@require_POST
def transition(request, pk):
    with transaction.atomic():
        document = _document(request, pk)
        document = Policy.objects.entire().select_for_update().get(pk=document.pk)
        action = request.POST.get("action")
        required = "delete" if action == "archive" else "change"
        if not can_manage_document(request.user, document, required):
            raise PermissionDenied
        if request.POST.get("revision") != document.updated_at.isoformat():
            return HttpResponse(
                _("This document changed. Reload before continuing."), status=409
            )
        if action not in ("archive", "unpublish"):
            return HttpResponse(_("Choose a valid document action."), status=400)
        document.is_visible_to_all = False
        document.is_active = action != "archive"
        document.modified_by = request.user
        document.save()
        audit_document(document, request.user, action)
    messages.success(
        request,
        _("Document archived.") if action == "archive" else _("Document unpublished."),
    )
    return redirect("company-document-detail", pk=pk)


@login_required
@never_cache
@require_http_methods(["GET"])
def file_response(request, pk, file_id):
    document = _document(request, pk)
    file = get_object_or_404(document.attachments, pk=file_id)
    if not file.is_active and not can_manage_document(request.user, document):
        raise Http404
    # Legacy files have no verified MIME; they are download-only.
    preview = request.GET.get("download") != "1" and file.can_preview
    try:
        stream = file.attachment.open("rb")
    except (OSError, ValueError):
        raise Http404(_("The file is not available. Please contact HR."))
    response = FileResponse(
        stream,
        as_attachment=not preview,
        filename=file.display_name,
        content_type=file.content_type or "application/octet-stream",
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return response


def _legacy_redirect(request, url_name, **kwargs):
    response = redirect(url_name, **kwargs)
    if request.headers.get("HX-Request"):
        response["HX-Redirect"] = response.url
    return response


@login_required
def legacy_detail(request):
    try:
        pk = int(request.GET.get("instance_id", ""))
    except ValueError:
        raise Http404
    _document(request, pk)
    return _legacy_redirect(request, "company-document-detail", pk=pk)


@login_required
def legacy_edit(request, pk=None):
    if pk is None and request.GET.get("instance_id"):
        try:
            pk = int(request.GET["instance_id"])
        except ValueError:
            raise Http404
    return edit(request, pk=pk)


@login_required
def legacy_attachments(request):
    try:
        pk = int(request.GET.get("policy_id", ""))
    except ValueError:
        raise Http404
    document = _document(request, pk)
    return render(request, "company_documents/files.html", {"document": document})


@login_required
@require_POST
def legacy_file_mutation(request):
    # Retired forms must use the editor with revision and publish intent.
    # In particular, never delete a file selected only by a caller-supplied ID.
    try:
        pk = int(request.GET.get("policy_id", ""))
    except ValueError:
        raise Http404
    document = _document(request, pk)
    if not can_manage_document(request.user, document, "change"):
        raise PermissionDenied
    return _legacy_redirect(request, "company-document-edit", pk=pk)


@login_required
@require_POST
def legacy_delete(request):
    return HttpResponse(
        _("Archive documents individually from Company documents."), status=409
    )


@login_required
def legacy_nav(request):
    return _legacy_redirect(request, "company-documents")
