"""HR settings and results using existing company roles."""

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from base.models import Company
from payroll.hr_access import can_manage_claim_reminders, can_email_payslip
from payroll.hr_delivery_models import (
    ClaimReminderPolicy,
    ClaimReminderDelivery,
    PayslipEmailDelivery,
)


class ClaimReminderForm(forms.ModelForm):
    class Meta:
        model = ClaimReminderPolicy
        fields = (
            "submission_enabled",
            "cutoff_day",
            "days_before",
            "submission_time",
            "approval_enabled",
            "approval_time",
            "include_admin",
            "timezone",
        )
        labels = {
            "submission_enabled": "Remind employees to submit claims",
            "cutoff_day": "Monthly cutoff day",
            "days_before": "Remind this many days before cutoff",
            "submission_time": "Employee reminder time",
            "approval_enabled": "Send a daily pending approval summary",
            "approval_time": "Approval summary time",
            "include_admin": "Also notify the Admin role",
        }
        widgets = {
            "submission_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "approval_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "timezone": forms.Select(choices=[("Asia/Singapore", "Singapore (UTC+8)")]),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "oh-input w-100"

    def clean_timezone(self):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        value = self.cleaned_data["timezone"]
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise forms.ValidationError("Choose a valid timezone.")
        return value


@login_required
@require_http_methods(["GET", "POST"])
def claim_reminder_settings(request):
    companies = [
        c
        for c in Company.objects.all()
        if can_manage_claim_reminders(request.user, c.pk)
    ]
    selected = (
        request.POST.get("company_id")
        or request.GET.get("company_id")
        or request.session.get("selected_company")
    )
    company = next((c for c in companies if str(c.pk) == str(selected)), None)
    if company is None and selected in (None, "", "all") and len(companies) == 1:
        company = companies[0]
    if not companies or (company is None and selected not in (None, "", "all")):
        return HttpResponseForbidden("HR access to this company is required.")
    form = None
    deliveries = []
    if company:
        policy = ClaimReminderPolicy.objects.filter(
            company=company
        ).first() or ClaimReminderPolicy(company=company)
        form = ClaimReminderForm(
            request.POST if request.method == "POST" else None, instance=policy
        )
        if request.method == "POST" and form.is_valid():
            policy = form.save(commit=False)
            policy.updated_by = request.user
            policy.base_url = request.build_absolute_uri("/").rstrip("/")
            policy.save()
            messages.success(request, "Claim reminder settings saved.")
            return redirect(request.path + f"?company_id={company.pk}")
        if policy.pk:
            deliveries = (
                ClaimReminderDelivery.objects.filter(policy=policy)
                .select_related("employee")
                .order_by("-attempted_at")[:30]
            )
    return render(
        request,
        "payroll/hr_delivery/claim_reminders.html",
        {
            "companies": companies,
            "company": company,
            "form": form,
            "deliveries": deliveries,
        },
    )


@login_required
def payslip_email_results(request, batch):
    deliveries = list(
        PayslipEmailDelivery.objects.filter(batch=batch).select_related(
            "employee__employee_work_info"
        )
    )
    if not deliveries:
        raise Http404
    from payroll.models.models import Payslip

    for item in deliveries:
        slips = list(
            Payslip.objects.entire()
            .filter(pk__in=item.payslip_ids)
            .select_related("employee_id__employee_work_info")
        )
        if not slips or any(
            not can_email_payslip(request.user, slip) for slip in slips
        ):
            return HttpResponseForbidden("You cannot view these email results.")
    from django.utils import timezone
    from datetime import timedelta

    pending = any(
        d.status == "pending" and d.attempted_at > timezone.now() - timedelta(minutes=5)
        for d in deliveries
    )
    retry_ids = [pk for d in deliveries if d.status == "failed" for pk in d.payslip_ids]
    return render(
        request,
        "payroll/hr_delivery/payslip_results.html",
        {"deliveries": deliveries, "pending": pending, "retry_ids": retry_ids},
    )
