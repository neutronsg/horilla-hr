"""Explicit, reasoned administrator handling of a pending leave request."""

from django import forms
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from horilla.decorators import login_required
from leave.locking import locked_leave_operation
from leave.models import LeaveRequest
from leave.workflow import can_admin_intervene


class InterventionForm(forms.Form):
    decision = forms.ChoiceField(
        choices=[("approve", "Approve"), ("reject", "Reject")],
        widget=forms.Select(attrs={"class": "oh-select w-100"}),
    )
    reason = forms.CharField(
        max_length=1000,
        strip=True,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "class": "oh-input w-100",
                "placeholder": "Why does this request need administrator handling?",
            }
        ),
        help_text="Explain why administrator intervention is needed. This is recorded in the leave audit trail.",
    )


@login_required
@locked_leave_operation("LeaveRequest")
def admin_intervention(request, id):
    item = get_object_or_404(LeaveRequest.objects, pk=id)
    if not can_admin_intervene(request.user, item):
        return HttpResponse(
            "Administrator intervention is unavailable for this request.", status=403
        )
    form = InterventionForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        from leave.views import leave_request_approve, leave_request_cancel

        request.leave_intervention_reason = form.cleaned_data["reason"]
        request.leave_intervention_id = item.pk
        try:
            if form.cleaned_data["decision"] == "approve":
                return leave_request_approve(request, item.pk)
            request.POST = request.POST.copy()
            request.POST["reason"] = form.cleaned_data["reason"]
            return leave_request_cancel(request, item.pk)
        finally:
            del request.leave_intervention_reason
            del request.leave_intervention_id
    return render(
        request,
        "leave/leave_request/admin_intervention.html",
        {"form": form, "item": item},
    )
