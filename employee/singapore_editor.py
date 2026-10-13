"""Restricted Singapore forms embedded in the general employee editor."""
import calendar
from datetime import date

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.forms.models import model_to_dict
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from employee.contributions import ContributionProfileForm
from employee.models import Employee
from employee.singapore import SingaporeDetailsForm, can_access_singapore_details
from employee.singapore_models import (
    SingaporeContributionProfile, SingaporeDetailsAudit, SingaporeEmployeeDetails,
)
from payroll.shg import applicable_funds, profile_for, uses_singapore_payroll


@sensitive_variables()
def editor_context(request, employee):
    """Keep separate saves, permissions, revisions and effective declaration history."""
    submitted = request.POST.get("form") if request.method == "POST" else None
    restricted_post = submitted in {"singapore_details", "singapore_contributions"}
    can_view = can_access_singapore_details(request, employee)
    can_edit = can_access_singapore_details(request, employee, edit=True)
    if restricted_post and not can_edit:
        raise PermissionDenied("You do not have access to edit Singapore employment details.")
    context = {"show_singapore_tab": can_view or uses_singapore_payroll(employee),
               "can_view_singapore_details": can_view, "can_edit_singapore_details": can_edit}
    if not can_view:
        return context
    try:
        month = date.fromisoformat(request.POST.get("salary_month") or request.GET.get("salary_month", ""))
        month = month.replace(day=1)
    except (ValueError, TypeError):
        month = timezone.localdate().replace(day=1)
    context["salary_month"] = month
    edit_details = can_edit and (request.GET.get("sg_edit") == "1" or submitted == "singapore_details")
    with transaction.atomic():
        if restricted_post:
            Employee.objects.entire().select_for_update().get(pk=employee.pk)
        details = SingaporeEmployeeDetails.objects.filter(employee=employee).first()
        details = details or SingaporeEmployeeDetails(employee=employee)
        latest = SingaporeContributionProfile.objects.filter(employee=employee).order_by("-created_at", "-pk").first()
        details_form = None
        contribution_form = None
        if submitted == "singapore_details":
            revision = details.updated_at.isoformat() if details.updated_at else ""
            details_form = SingaporeDetailsForm(request.POST, instance=details, prefix="sg")
            if details_form.is_valid():
                if details_form.cleaned_data["revision"] != revision:
                    details_form.add_error(None, "This record changed while you were editing. Reload before saving.")
                else:
                    fields = [field for field in details_form.changed_data if field != "revision"]
                    details_form.save()
                    SingaporeDetailsAudit.objects.create(employee=employee, actor=request.user,
                        action="update", fields=fields)
                    messages.success(request, "Singapore employment details saved.")
                    details_form = None
                    edit_details = False
        if submitted == "singapore_contributions":
            contribution_form = ContributionProfileForm(request.POST, prefix="shg", previous=latest,
                instance=SingaporeContributionProfile(employee=employee, created_by=request.user), details=details)
            if contribution_form.is_valid():
                if contribution_form.cleaned_data["revision"] != (str(latest.pk) if latest else ""):
                    contribution_form.add_error(None, "This declaration changed while you were editing. Reload before saving.")
                else:
                    latest = contribution_form.save()
                    SingaporeDetailsAudit.objects.create(employee=employee, actor=request.user,
                        action="update_contribution", fields=list(ContributionProfileForm.Meta.fields) + ["fund_selection", "fund_adjustments"])
                    messages.success(request, "Contribution settings saved. Payroll applies them automatically; existing payslips are unchanged.")
                    contribution_form = None
        if can_edit:
            if details_form is None and edit_details:
                details_form = SingaporeDetailsForm(instance=details, prefix="sg")
            if contribution_form is None:
                initial = model_to_dict(latest, fields=ContributionProfileForm.Meta.fields) if latest else {
                    name: getattr(details, name) for name in ("residency_status", "pr_effective_date", "work_pass_type")}
                if initial.get("declaration_reference") == "HR contribution settings":
                    initial["declaration_reference"] = ""
                initial.update(effective_month=month, revision=str(latest.pk) if latest else "")
                contribution_form = ContributionProfileForm(prefix="shg", previous=latest, initial=initial,
                    instance=SingaporeContributionProfile(employee=employee, created_by=request.user), details=details)
        current = profile_for(employee, month)
        month_end = month.replace(day=calendar.monthrange(month.year, month.month)[1])
        context.update(singapore_details=details, singapore_details_form=details_form,
            contribution_form=contribution_form, contribution_profile=current,
            contribution_funds=applicable_funds(current, month_end) if current else [],
            contribution_latest=latest, edit_singapore_details=edit_details)
        if request.method == "GET":
            SingaporeDetailsAudit.objects.create(employee=employee, actor=request.user,
                action="view_full" if edit_details else "view_masked", fields=[])
            SingaporeDetailsAudit.objects.create(employee=employee, actor=request.user,
                action="view_contribution", fields=[])
    return context
