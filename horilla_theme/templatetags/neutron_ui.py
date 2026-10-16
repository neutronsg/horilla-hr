"""Presentation labels; never used for authorization or model values."""
import re

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

register = template.Library()


@register.filter
def display_cell(value):
    return "—" if value is None or value == "None" else value


@register.filter
def primary_profile_tab(value):
    return str(value) in {_(label) for label in ("About", "Documents", "Leave", "Payroll", "History")}


@register.filter
def workspace_label(value, keep_case=False):
    """
    Navigation label for display. ``keep_case`` is for names that are data, not
    labels (a record shown in the breadcrumb, the company): they are mapped but
    never re-cased, so "Alex Morgan" stays "Alex Morgan".
    """
    labels = {
        "Horilla": "Neutron HR", "employee-view": "Employees",
        "employee-view-update": "Edit employee", "employee-profile": "Employee profile",
        "view-payslip": "Payslip", "payslip-view": "Payslips",
        "view-reimbursement": "Claims", "reimbursement-view": "Claims",
        "request-view": "Leave requests", "leave-request-view": "Leave requests",
        "dashboard-view": "Overview", "dashboard": "Overview",
        "Feedbacks": "Feedback", "360 Feedback": "Feedback",
        "Attendances": "Attendance", "My Leave requests": "My leave requests",
        "My Leave Requests": "My leave requests", "Employee Bonus Point": "Bonus points",
        "Employee Bonus Points": "Bonus points", "Bonus Points": "Bonus points",
        "Leave Allocation Request": "Leave allocation requests", "Leave Allocation Requests": "Leave allocation requests",
        "Requests & Allocation": "Asset requests and allocations",
        "Encashments & Reimbursements": "Claims", "Timesheet": "Timesheets",
        "employee-bonus-point": "Bonus points", "feedback-view": "Feedback",
        "leave-allocation-request-view": "Leave allocation requests",
        "asset-request-allocation-view": "Asset requests and allocations",
        "user-request-view": "My leave requests", "view-time-sheet": "Timesheets",
    }
    labels.update({
        "Employee bonus point": "Bonus points", "Asset": "Asset requests and allocations",
        "Asset Category": "Assets", "Asset batch number": "Asset batches",
        "Reimbursements": "Claims", "Filing status": "Filing statuses", "Income Tax": "Filing statuses",
        "All leave balances": "Leave balances", "Scheduled interviews": "Interviews",
        "Employee": "Employees", "Project": "Projects",
        "recruitment-view": "Job openings", "filing-status-view": "Filing statuses",
        "asset-category-view": "Assets", "asset-batch-view": "Asset batches",
    })
    text = str(value).strip()
    for source, target in labels.items():
        if text.casefold() == str(_(source)).casefold():
            return _(target)
    if text in labels:
        return _(labels[text])
    if text == text.lower() and " " not in text:
        # A URL slug ("system-preferences-view", "settings"): drop "view" and
        # sentence-case what is left.
        words = [w for w in text.replace("_", "-").split("-") if w and w != "view"]
        return " ".join(words).capitalize() if words else text
    # Presentation only: labels are already translated, so preserve acronyms and
    # proper nouns while bringing English title-case navigation into sentence case.
    if text and text.isascii() and not keep_case:
        words = text.split()
        text = " ".join(word if i == 0 or word.isupper() else word.lower() for i, word in enumerate(words))
    return text


# Sidebar grouping. Menus still come from each app's sidebar.py with its own
# accessibility checks; this only orders and labels what the user may already see.
NAV_GROUPS = (
    ("people", gettext_lazy("People"), ("employee", "recruitment", "onboarding", "offboarding")),
    ("time", gettext_lazy("Time"), ("attendance", "leave", "biometric")),
    ("pay", gettext_lazy("Pay"), ("payroll",)),
    ("work", gettext_lazy("Work"), ("pms", "project", "asset", "helpdesk")),
    ("insights", gettext_lazy("Insights"), ("report",)),
)


# Sidebar sections that only hold check-in data; hidden while check-in is disabled.
ATTENDANCE_APPS = ("attendance", "biometric")


def attendance_tracking(request):
    """Whether the selected company records attendance (check-in enabled), once per request."""
    if request is None:
        return True
    from base.dashboard import attendance_tracking_enabled
    from horilla.request_cache import request_value

    return request_value(request, "neutron.attendance_tracking", lambda: attendance_tracking_enabled(request))


@register.simple_tag(takes_context=True)
def neutron_nav_groups(context, menus):
    """Return [(label, [menu, ...]), ...] in a stable order; unknown apps go last."""
    menus = list(menus or [])
    if not attendance_tracking(context.get("request")):
        menus = [m for m in menus if m.get("app") not in ATTENDANCE_APPS]
    placed, groups = set(), []
    for _key, label, apps in NAV_GROUPS:
        items = [m for app in apps for m in menus if m.get("app") == app]
        placed.update(id(m) for m in items)
        if items:
            groups.append((label, items))
    rest = [m for m in menus if id(m) not in placed]
    if rest:
        groups.append((gettext_lazy("More"), rest))
    return groups


# 24px outline icons (Lucide-style shapes), inlined so they inherit colour and need no font or CDN.
ICONS = {
    "close": '<path d="m6 6 12 12M6 18 18 6"/>',
    "check_all": '<path d="m2 12 4 4L16 6M12 16l10-10"/>',
    "dashboard": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "employee": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    "recruitment": '<rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2M2 13h20"/>',
    "onboarding": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="m16 11 2 2 4-4"/>',
    "offboarding": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 11h-6"/>',
    "attendance": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "leave": '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    "biometric": '<path d="M12 10a2 2 0 0 0-2 2c0 1.02-.1 2.51-.26 4M14 13.12c0 2.38 0 6.38-1 8.88M17.29 21.02c.12-.6.43-2.3.5-3.02M2 12a10 10 0 0 1 18-6M2 16h.01M21.8 16c.2-2 .131-5.354 0-6M5 19.5C5.5 18 6 15 6 12a6 6 0 0 1 .34-2M8.65 22c.21-.66.45-1.32.57-2M9 6.8a6 6 0 0 1 9 5.2v2"/>',
    "payroll": '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="2.5"/><path d="M6 12h.01M18 12h.01"/>',
    "pms": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
    "project": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
    "asset": '<rect x="4" y="5" width="16" height="11" rx="1.5"/><path d="M2 20h20"/>',
    "helpdesk": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/><path d="m5.6 5.6 3.6 3.6M14.8 14.8l3.6 3.6M14.8 9.2l3.6-3.6M5.6 18.4l3.6-3.6"/>',
    "report": '<path d="M3 3v18h18"/><path d="M8 17v-5M13 17V8M18 17v-9"/>',
    "plus": '<path d="M5 12h14M12 5v14"/>',
    "building": '<rect x="4" y="2" width="16" height="20" rx="1.5"/><path d="M9 22v-4h6v4M8 6h.01M12 6h.01M16 6h.01M8 10h.01M12 10h.01M16 10h.01M8 14h.01M12 14h.01M16 14h.01"/>',
    "chevrons": '<path d="m7 15 5 5 5-5M7 9l5-5 5 5"/>',
    "settings": '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
    "bell": '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01"/>',
    "moon": '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    "receipt": '<path d="M5 2v20l2.3-1.5L9.7 22l2.3-1.5 2.3 1.5 2.4-1.5L19 22V2l-2.3 1.5L14.3 2 12 3.5 9.7 2 7.3 3.5Z"/><path d="M15 8H9M15 12H9M13 16H9"/>',
    "ticket": '<path d="M2 9a3 3 0 0 0 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-2a3 3 0 0 0 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z"/><path d="M13 5v2M13 17v2M13 11v2"/>',
    "briefcase": '<rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/>',
    "history": '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l4 2"/>',
    "clock_plus": '<path d="M21 12a9 9 0 1 0-9 9"/><path d="M12 7v5l3 2M19 16v6M16 19h6"/>',
    "chevron_down": '<path d="m6 9 6 6 6-6"/>',
}


@register.simple_tag
def neutron_icon(name, size=16):
    shape = ICONS.get(str(name))
    if not shape:
        return ""
    return format_html(
        '<svg class="neutron-icon" width="{0}" height="{0}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{1}</svg>',
        size,
        mark_safe(shape),
    )


_STYLE_ATTRIBUTE = re.compile(r"""((?<![\w-])style\s*=\s*)(["'])(.*?)\2""", re.IGNORECASE | re.DOTALL)
# A whole declaration whose property is exactly width, min-width or max-width.
_WIDTH_DECLARATION = re.compile(r"(?:(?<=;)|^)\s*(?:min-|max-)?width\s*:[^;]*(?:;|$)", re.IGNORECASE)


@register.filter
def strip_column_widths(attrs):
    """
    Drop fixed width declarations from the style attribute of a list view's
    header_attrs. Widths were tuned for the old fixed, truncating table layout;
    columns now size to their content. Other declarations and attributes are
    kept as written.
    """
    if not attrs:
        return attrs

    def clean(match):
        declarations = _WIDTH_DECLARATION.sub("", match.group(3)).strip()
        return f"{match.group(1)}{match.group(2)}{declarations}{match.group(2)}"

    return _STYLE_ATTRIBUTE.sub(clean, str(attrs))


_HEX_COLOUR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_PRIMARY_STEPS = (50, 100, 200, 300, 400, 500, 600, 700, 800, 900)


@register.simple_tag
def neutron_theme_vars(theme):
    """
    Emit the company theme's primary scale as CSS variables, after neutron.css.
    neutron.css carries the Neutron palette as the default; a company theme
    overrides it here. Values that are not plain hex colours are skipped.
    """
    if not theme:
        return ""
    declarations = []
    for step in _PRIMARY_STEPS:
        value = str(getattr(theme, f"primary_{step}", "") or "")
        if _HEX_COLOUR.match(value):
            declarations.append(f"--primary-{step}:{value};")
    if not declarations:
        return ""
    return mark_safe(f"<style id=\"neutron-theme-vars\">:root{{{''.join(declarations)}}}</style>")


@register.simple_tag
def company_calendar_today():
    """Today's date for the company leave calendar (Singapore time), as ISO text."""
    from base.company_leave_calendar import _today

    return _today().isoformat()


@register.simple_tag(takes_context=True)
def neutron_home_url(context):
    """
    The sidebar's Dashboard link: the analytics overview for HR, managers and
    leadership, the personal dashboard for everyone else (no redirect hop).
    """
    from django.urls import reverse

    from horilla.request_cache import request_value

    request = context.get("request")
    if request is None or not getattr(request, "user", None) or not request.user.is_authenticated:
        return reverse("dashboard")

    def compute():
        try:
            from base.dashboard_roles import can_see_analytics_home, resolve_home_role

            if not can_see_analytics_home(resolve_home_role(request)):
                return reverse("ess-dashboard")
        except Exception:
            pass
        return reverse("dashboard")

    return request_value(request, "neutron.home_url", compute)


@register.filter
def breadcrumb_items(breadcrumbs):
    """
    Breadcrumbs with their display label. Records (an employee, a payslip) and the
    company are names shown as written; navigation crumbs use the shared label
    wording. When a module and its list read the same ("Employees > Employees"),
    only the later, more specific crumb is kept.
    """
    items = []
    for index, crumb in enumerate(breadcrumbs or []):
        name = crumb.get("name", "")
        if crumb.get("record"):
            label = str(name)
        else:
            label = str(workspace_label(name, keep_case=index == 0))
        items.append({**crumb, "label": label})
    return [
        item for index, item in enumerate(items)
        if index + 1 >= len(items) or item["label"] != items[index + 1]["label"]
    ]
