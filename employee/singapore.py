"""Explicit, company-scoped access to Singapore employment information."""

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods

from base.auth_backends import get_allowed_company_ids
from employee.models import Employee
from employee.singapore_models import SingaporeDetailsAudit, SingaporeEmployeeDetails


class SingaporeDetailsForm(forms.ModelForm):
    revision = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = SingaporeEmployeeDetails
        fields = (
            "identity_type", "identity_number", "residency_status", "pr_effective_date",
            "work_pass_type", "work_pass_number", "work_pass_expiry", "personal_email",
        )
        labels = {"identity_number": "NRIC / FIN number", "work_pass_type": "Pass type"}
        widgets = {
            "pr_effective_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "work_pass_expiry": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "identity_number": forms.TextInput(attrs={"autocomplete": "off"}),
            "work_pass_number": forms.TextInput(attrs={"autocomplete": "off"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.updated_at:
            self.initial["revision"] = self.instance.updated_at.isoformat()
        for field in self.fields.values():
            field.widget.attrs["class"] = "oh-input w-100"


def can_access_singapore_details(request, employee, *, edit=False):
    user = request.user
    if not user.is_authenticated or not user.is_active:
        return False
    company_id = getattr(getattr(employee, "employee_work_info", None), "company_id_id", None)
    if company_id is None:
        return False
    if not user.is_superuser and company_id not in get_allowed_company_ids(user):
        return False
    if not user.has_perm("employee.view_singaporeemployeedetails"):
        return False
    return not edit or user.has_perm("employee.change_singaporeemployeedetails")


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
@sensitive_post_parameters("identity_number", "work_pass_number", "personal_email")
@sensitive_variables()
def singapore_details(request, pk):
    employee = get_object_or_404(Employee.objects.entire(), pk=pk)
    edit = request.method == "POST" or request.GET.get("edit") == "1"
    if not can_access_singapore_details(request, employee, edit=edit):
        return HttpResponseForbidden("You do not have access to Singapore employment details.")
    with transaction.atomic():
        # Lock the parent as well: it exists before the optional details row.
        Employee.objects.entire().select_for_update().get(pk=pk)
        details = SingaporeEmployeeDetails.objects.filter(employee=employee).first()
        details = details or SingaporeEmployeeDetails(employee=employee)
        form = SingaporeDetailsForm(request.POST if request.method == "POST" else None, instance=details)
        if request.method == "POST" and form.is_valid():
            revision = details.updated_at.isoformat() if details.updated_at else ""
            if form.cleaned_data["revision"] != revision:
                form.add_error(None, "This record changed while you were editing. Reload before saving.")
            else:
                fields = [f for f in form.changed_data if f != "revision"]
                form.save()
                SingaporeDetailsAudit.objects.create(
                    employee=employee, actor=request.user, action="update", fields=fields
                )
                messages.success(request, "Singapore employment details saved.")
                return redirect("singapore-employee-details", pk=pk)
        if request.method == "GET":
            SingaporeDetailsAudit.objects.create(
                employee=employee, actor=request.user,
                action="view_full" if edit else "view_masked", fields=[]
            )
        # No form (including its initial plaintext) is passed to the read-only template.
        context = {
            "employee": employee, "details": details, "edit": edit,
            "can_edit": can_access_singapore_details(request, employee, edit=True),
            "form": form if edit else None,
            "audit_events": SingaporeDetailsAudit.objects.filter(employee=employee).select_related("actor")[:10],
        }
        return render(request, "employee/singapore/details.html", context)
