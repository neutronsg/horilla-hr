"""Actionable payroll validation messages without exposing declaration values."""
from urllib.parse import urlencode

from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext as _


def payroll_validation_message(employee, error, salary_date):
    message = "; ".join(error.messages)
    if any(item.code == "missing_shg_profile" for item in getattr(error, "error_list", ())):
        url = reverse("employee-view-update", args=[employee.pk]) + "?" + urlencode({
            "tab": "singapore", "salary_month": salary_date.replace(day=1).isoformat(),
        })
        return format_html('{}: {} <a href="{}">{}</a>', employee.get_full_name(), message,
            url, _("Review Singapore employment"))
    return format_html("{}: {}", employee.get_full_name(), message)
