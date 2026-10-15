"""Presentation labels; never used for authorization or model values."""
from django import template
from django.utils.translation import gettext as _

register = template.Library()


@register.filter
def display_cell(value):
    return "—" if value is None or value == "None" else value


@register.filter
def primary_profile_tab(value):
    return str(value) in {_(label) for label in ("About", "Documents", "Leave", "Payroll", "History")}


@register.filter
def workspace_label(value):
    labels = {
        "Horilla": "Neutron HR", "employee-view": "Directory",
        "employee-view-update": "Edit employee", "employee-profile": "Employee profile",
        "view-payslip": "Payslip", "payslip-view": "Payslips",
        "view-reimbursement": "Claims", "reimbursement-view": "Claims",
        "request-view": "Leave requests", "leave-request-view": "Leave requests",
        "dashboard-view": "Overview", "dashboard": "Overview",
    }
    text = str(value)
    if text in labels:
        return _(labels[text])
    if text == text.lower() and " " not in text and ("-" in text or "_" in text):
        return text.replace("-", " ").replace("_", " ").capitalize()
    return text
