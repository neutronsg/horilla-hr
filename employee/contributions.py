"""Private, append-only SHG declarations under the existing Singapore HR permissions."""
import calendar
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.forms.models import model_to_dict
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods

from employee.models import Employee
from employee.singapore import can_access_singapore_details
from employee.singapore_models import SingaporeContributionProfile, SingaporeDetailsAudit, SingaporeEmployeeDetails
from payroll.shg import FUNDS, applicable_funds, profile_for, validate_adjustments

TREATMENTS = [("auto", "Automatic statutory calculation"), ("opt_out", "Documented opt-out"),
              ("fixed", "Approved fixed contribution"), ("voluntary", "Requested voluntary contribution")]

class ContributionProfileForm(forms.ModelForm):
    revision = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = SingaporeContributionProfile
        fields = ("effective_month", "primary_race", "muslim_status", "residency_status",
                  "pr_effective_date", "work_pass_type", "declaration_reference",
                  "student_cpf_exempt", "student_mbmf_exempt", "student_exempt_from",
                  "student_exempt_until", "student_exemption_reference")
        widgets = {name: forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
                   for name in ("effective_month", "pr_effective_date", "student_exempt_from", "student_exempt_until")}
        help_texts = {
            "effective_month": "Use the first day of the salary month. Saving creates a new version; existing payslips stay unchanged.",
            "primary_race": "Use the first race on NRIC for a double-barrelled race, or the employee's declaration. Do not infer it from a name.",
            "declaration_reference": "Reference to the verified declaration / record, without copying identity numbers here.",
            "student_cpf_exempt": "Only qualifying institution training with retained evidence; an Intern job title alone does not qualify. Also record the CPF exemption on the contract.",
            "student_mbmf_exempt": "Check MUIS student exemption rules separately from CPF.",
        }

    def __init__(self, *args, **kwargs):
        previous = kwargs.pop("previous", None)
        super().__init__(*args, **kwargs)
        for fund in FUNDS:
            adjustment = previous.fund_adjustments.get(fund, {}) if previous else {}
            self.fields[f"{fund}_mode"] = forms.ChoiceField(label=f"{fund.upper()} treatment",
                choices=TREATMENTS,
                initial=adjustment.get("mode", "auto"))
            self.fields[f"{fund}_amount"] = forms.DecimalField(required=False,
                min_value=Decimal(".01"), max_value=Decimal("99999.99"), decimal_places=2, max_digits=7,
                label="Monthly amount", initial=adjustment.get("amount"))
            self.fields[f"{fund}_reference"] = forms.CharField(required=False, max_length=255,
                label="Application / certificate reference", initial=adjustment.get("reference", ""))
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "oh-input w-100"

    def clean(self):
        cleaned = super().clean()
        adjustments = {}
        for fund in FUNDS:
            mode = cleaned.get(f"{fund}_mode")
            amount, reference = cleaned.get(f"{fund}_amount"), cleaned.get(f"{fund}_reference", "")
            if mode == "auto":
                if amount is not None or reference:
                    self.add_error(f"{fund}_mode", "Clear the amount and reference when using automatic calculation.")
            elif mode:
                if not reference:
                    self.add_error(f"{fund}_reference", "Record the application / certificate reference.")
                if mode == "opt_out" and amount is not None:
                    self.add_error(f"{fund}_amount", "Opt-out must not specify an amount.")
                elif mode != "opt_out" and amount is None:
                    self.add_error(f"{fund}_amount", "Specify the approved monthly contribution.")
                adjustments[fund] = {"mode": mode, "reference": reference}
                if amount is not None:
                    adjustments[fund]["amount"] = str(amount)
        if not self.errors:
            try:
                validate_adjustments(adjustments)
            except ValidationError as exc:
                self.add_error(None, exc)
        # Model validation sees the structured values; no JSON editor is exposed.
        self.instance.fund_adjustments = adjustments if not self.errors else {}
        return cleaned

    def _post_clean(self):
        super()._post_clean()
        if self.errors:
            return
        month = self.instance.effective_month
        end = month.replace(day=calendar.monthrange(month.year, month.month)[1])
        eligible = applicable_funds(self.instance, end)
        for fund, adjustment in self.instance.fund_adjustments.items():
            if adjustment["mode"] == "fixed" and fund not in eligible:
                self.add_error(f"{fund}_mode", "This fund is not applicable. Use documented voluntary treatment if requested.")

    @property
    def declaration_fields(self):
        return [self[name] for name in self.Meta.fields[:7]]

    @property
    def student_fields(self):
        return [self[name] for name in self.Meta.fields[7:]]

    @property
    def fund_fields(self):
        return [{"name": fund.upper(), "mode": self[f"{fund}_mode"],
                 "amount": self[f"{fund}_amount"], "reference": self[f"{fund}_reference"]} for fund in FUNDS]


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
@sensitive_post_parameters()
@sensitive_variables()
def singapore_contributions(request, pk):
    employee = get_object_or_404(Employee.objects.entire(), pk=pk)
    edit = request.method == "POST" or request.GET.get("edit") == "1"
    if not can_access_singapore_details(request, employee, edit=edit):
        return HttpResponseForbidden("You do not have access to Singapore contribution details.")
    with transaction.atomic():
        Employee.objects.entire().select_for_update().get(pk=pk)
        history = SingaporeContributionProfile.objects.filter(employee=employee).select_related("created_by")
        latest = history.order_by("-created_at", "-pk").first()
        today = timezone.localdate()
        current = profile_for(employee, today)
        selected_version = request.GET.get("version")
        if selected_version and not edit:
            if not selected_version.isdigit() or len(selected_version) > 18:
                from django.http import Http404
                raise Http404
            current = get_object_or_404(history, pk=int(selected_version))
        period_end = current.effective_month.replace(day=calendar.monthrange(current.effective_month.year, current.effective_month.month)[1]) if selected_version and current else today
        initial = model_to_dict(latest, fields=ContributionProfileForm.Meta.fields) if latest else {}
        if not latest:
            details = SingaporeEmployeeDetails.objects.filter(employee=employee).first()
            if details:
                initial.update({name: getattr(details, name) for name in ("residency_status", "pr_effective_date", "work_pass_type")})
        initial.update(effective_month=today.replace(day=1), revision=str(latest.pk) if latest else "")
        form = ContributionProfileForm(request.POST if request.method == "POST" else None,
            instance=SingaporeContributionProfile(employee=employee, created_by=request.user),
            initial=initial, previous=latest)
        if request.method == "POST" and form.is_valid():
            if form.cleaned_data["revision"] != initial["revision"]:
                form.add_error(None, "This declaration changed while you were editing. Reload before saving.")
            else:
                form.save()
                SingaporeDetailsAudit.objects.create(employee=employee, actor=request.user,
                    action="update_contribution", fields=list(ContributionProfileForm.Meta.fields) + ["fund_adjustments"])
                messages.success(request, "Contribution declaration saved. Existing payslips are unchanged.")
                return redirect("singapore-employee-contributions", pk=pk)
        if request.method == "GET":
            SingaporeDetailsAudit.objects.create(employee=employee, actor=request.user,
                action="view_contribution", fields=[])
        return render(request, "employee/singapore/contributions.html", {
            "employee": employee, "edit": edit, "form": form if edit else None,
            "current": current, "selected_version": bool(selected_version),
            "funds": applicable_funds(current, period_end) if current else [],
            "history": history[:20], "can_edit": can_access_singapore_details(request, employee, edit=True),
            "adjustments": [{"fund": fund.upper(), **item, "label": dict(TREATMENTS)[item["mode"]]}
                for fund, item in current.fund_adjustments.items()] if current else [],
        })
