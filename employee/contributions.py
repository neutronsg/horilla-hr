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

class LegacyContributionProfileForm(forms.ModelForm):
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
        self.fields["primary_race"].required = True
        self.fields["muslim_status"].required = True
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


FUND_SETTINGS = [("", "Choose a setting"), ("auto", "Contribute · standard rate"),
                 ("not_applicable", "Not applicable"), ("opt_out", "Documented opt-out"),
                 ("fixed", "Approved monthly amount"), ("voluntary", "Voluntary contribution"),
                 ("student_exempt", "Student exemption · dated")]
FUND_NAMES = {"cdac": "Chinese Development Assistance Council", "ecf": "Eurasian Community Fund",
              "sinda": "Singapore Indian Development Association", "mbmf": "Mosque Building and Mendaki Fund"}


class ContributionProfileForm(forms.ModelForm):
    """Configure verified fund eligibility directly, without demographic questions."""
    revision = forms.CharField(required=False, widget=forms.HiddenInput)
    configuration_version = forms.ChoiceField(choices=[("funds-v3", "funds-v3")], initial="funds-v3", widget=forms.HiddenInput)
    use_start_month = forms.BooleanField(required=False, label="Use a specific start month")
    start_month = forms.DateField(required=False, label="Applies from", input_formats=["%Y-%m", "%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "month"}, format="%Y-%m"))
    declaration_reference = forms.CharField(required=False, max_length=255, label="Note (optional)")

    class Meta:
        model = SingaporeContributionProfile
        fields = ("declaration_reference", "student_exempt_from",
                  "student_exempt_until", "student_exemption_reference")
        labels = {"declaration_reference": "Verification reference", "student_exempt_from": "Exemption starts",
                  "student_exempt_until": "Exemption ends", "student_exemption_reference": "Exemption evidence"}
        widgets = {name: forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
                   for name in ("student_exempt_from", "student_exempt_until")}

    def __init__(self, *args, **kwargs):
        previous = kwargs.pop("previous", None)
        details = kwargs.pop("details", None)
        super().__init__(*args, **kwargs)
        if self.is_bound and self.data.get(self.add_prefix("configuration_version")) != "funds-v3":
            # A pre-upgrade demographic form used Auto on every fund. Never
            # reinterpret that old payload as four explicit fund selections.
            data = self.data.copy()
            for fund in FUNDS:
                data[self.add_prefix(f"{fund}_mode")] = ""
            self.data = data
        # Residency remains the source for CPF and PR transition wage calculations.
        source = details if details and details.residency_status else previous
        for name in ("residency_status", "pr_effective_date", "work_pass_type"):
            setattr(self.instance, name, getattr(source, name, "" if name != "pr_effective_date" else None))
        eligible = applicable_funds(previous, previous.effective_month.replace(
            day=calendar.monthrange(previous.effective_month.year, previous.effective_month.month)[1])) if previous else []
        for fund in FUNDS:
            adjustment = previous.fund_adjustments.get(fund, {}) if previous else {}
            mode = adjustment.get("mode", "auto" if fund in eligible else "not_applicable") if previous else ""
            if previous and mode == "auto" and ((fund == "mbmf" and previous.student_mbmf_exempt)
                    or (fund != "mbmf" and previous.student_cpf_exempt)):
                mode = "student_exempt"
            self.fields[f"{fund}_mode"] = forms.ChoiceField(label=f"{fund.upper()} contribution",
                choices=FUND_SETTINGS, initial=mode)
            self.fields[f"{fund}_amount"] = forms.DecimalField(required=False, min_value=Decimal(".01"),
                max_value=Decimal("99999.99"), decimal_places=2, max_digits=7, label="Monthly amount (S$)",
                initial=adjustment.get("amount"))
            self.fields[f"{fund}_reference"] = forms.CharField(required=False, max_length=255,
                label="Approval reference", initial=adjustment.get("reference", ""))
        for field in self.fields.values():
            if not isinstance(field.widget, forms.HiddenInput):
                field.widget.attrs["class"] = "sg-input"
        self.fields["declaration_reference"].widget.attrs["placeholder"] = "Add a note if needed"
        self.fields["use_start_month"].widget.attrs["data-start-month-toggle"] = ""

    def clean(self):
        cleaned = super().clean()
        month = timezone.localdate().replace(day=1)
        if cleaned.get("use_start_month"):
            if not cleaned.get("start_month"):
                self.add_error("start_month", "Choose the month this change should start.")
            elif cleaned["start_month"].day != 1:
                self.add_error("start_month", "Use the first day of the start month.")
            else:
                month = cleaned["start_month"]
        self.instance.effective_month = month
        self.instance.is_baseline = (
            not cleaned.get("use_start_month")
            and not SingaporeContributionProfile.objects.filter(employee=self.instance.employee, is_baseline=True).exists()
        )
        cleaned["declaration_reference"] = cleaned.get("declaration_reference", "").strip() or "HR contribution settings"
        if not cleaned.get("configuration_version"):
            self.add_error(None, "The contribution form has changed. Reload the page before saving.")
        selection, adjustments = {}, {}
        exempt = set()
        for fund in FUNDS:
            mode = cleaned.get(f"{fund}_mode")
            selection[fund] = mode in {"auto", "fixed", "opt_out", "student_exempt"}
            amount, reference = cleaned.get(f"{fund}_amount"), cleaned.get(f"{fund}_reference", "")
            if mode in {"auto", "not_applicable", "student_exempt"}:
                if amount is not None or reference:
                    self.add_error(f"{fund}_mode", "Clear the amount and approval reference for this setting.")
            elif mode in {"fixed", "voluntary", "opt_out"}:
                if not reference:
                    self.add_error(f"{fund}_reference", "Record the approval or employee request reference.")
                if mode == "opt_out" and amount is not None:
                    self.add_error(f"{fund}_amount", "An opt-out cannot have a contribution amount.")
                elif mode != "opt_out" and amount is None:
                    self.add_error(f"{fund}_amount", "Enter the approved monthly amount.")
                adjustments[fund] = {"mode": mode, "reference": reference}
                if amount is not None:
                    adjustments[fund]["amount"] = str(amount)
            if mode == "student_exempt":
                exempt.add(fund)
        self.instance.fund_selection = selection
        self.instance.fund_adjustments = adjustments if not self.errors else {}
        self.instance.student_cpf_exempt = bool(exempt - {"mbmf"})
        self.instance.student_mbmf_exempt = "mbmf" in exempt
        if self.instance.student_cpf_exempt:
            for fund in ("cdac", "ecf", "sinda"):
                if cleaned.get(f"{fund}_mode") in {"auto", "fixed"}:
                    self.add_error(f"{fund}_mode", "Use the student exemption for each applicable CDAC / ECF / SINDA fund.")
        if not exempt:
            for name in ("student_exempt_from", "student_exempt_until", "student_exemption_reference"):
                if cleaned.get(name):
                    self.add_error(name, "Clear exemption details when no student exemption is selected.")
        if not self.instance.residency_status:
            self.add_error(None, "Save the employee's residency in employment details before configuring contributions.")
        if self.instance.residency_status == "foreigner" and not self.instance.work_pass_type:
            self.add_error(None, "Save the employee's work-pass type in employment details first.")
        return cleaned

    def _update_errors(self, errors):
        # Residency is read from employment details, so its validation belongs in
        # the form summary rather than a field that is not part of this editor.
        if hasattr(errors, "error_dict"):
            mapped = {}
            for name, items in errors.error_dict.items():
                target = name if name in self.fields else "__all__"
                mapped.setdefault(target, []).extend(items)
            errors = ValidationError(mapped)
        super()._update_errors(errors)

    @property
    def fund_fields(self):
        return [{"name": fund.upper(), "description": FUND_NAMES[fund], "mode": self[f"{fund}_mode"],
                 "amount": self[f"{fund}_amount"], "reference": self[f"{fund}_reference"]} for fund in FUNDS]

    @property
    def declaration_fields(self):
        return [self["declaration_reference"]]

    @property
    def student_fields(self):
        return [self[name] for name in self.Meta.fields[1:]]


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
        if initial.get("declaration_reference") == "HR contribution settings":
            initial["declaration_reference"] = ""
        initial.update(effective_month=today.replace(day=1), revision=str(latest.pk) if latest else "")
        form = ContributionProfileForm(request.POST if request.method == "POST" else None,
            instance=SingaporeContributionProfile(employee=employee, created_by=request.user),
            initial=initial, previous=latest, details=SingaporeEmployeeDetails.objects.filter(employee=employee).first())
        if request.method == "POST" and form.is_valid():
            if form.cleaned_data["revision"] != initial["revision"]:
                form.add_error(None, "This declaration changed while you were editing. Reload before saving.")
            else:
                form.save()
                SingaporeDetailsAudit.objects.create(employee=employee, actor=request.user,
                    action="update_contribution", fields=list(ContributionProfileForm.Meta.fields) + ["fund_selection", "fund_adjustments", "effective_month", "is_baseline"])
                messages.success(request, "Contribution settings saved. Payroll applies them automatically; existing payslips are unchanged.")
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
