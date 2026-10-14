"""Employee-owned probation state and the company early annual-leave benefit."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from horilla.horilla_middlewares import _thread_locals

FIELDS = ("probation_status", "probation_end", "probation_passed_on")


def can_manage_probation(user, company_id):
    if not user or not user.is_authenticated or not user.is_active or not company_id:
        return False
    if user.is_superuser:
        return True
    from base.auth_backends import (
        get_user_groups_for_company,
        get_effective_permission_codenames,
    )

    return get_user_groups_for_company(user, company_id).filter(
        name__in=("HR Manager", "Admin")
    ).exists() and bool(
        {"change_employee", "change_employeeworkinformation"}
        & set(get_effective_permission_codenames(user, company_id))
    )


def validate_probation(work):
    errors = {}
    status = work.probation_status or "not_recorded"
    if (
        work.probation_end
        and work.date_joining
        and work.probation_end < work.date_joining
    ):
        errors["probation_end"] = _(
            "Expected probation end cannot be before the joining date."
        )
    if status == "passed":
        if not work.date_joining:
            errors["date_joining"] = _(
                "Set the joining date before confirming probation."
            )
        if not work.probation_passed_on:
            errors["probation_passed_on"] = _(
                "Enter the actual probation confirmation date."
            )
        elif work.probation_passed_on > timezone.localdate():
            errors["probation_passed_on"] = _(
                "Confirmation must have happened; the date cannot be in the future."
            )
        elif work.date_joining and work.probation_passed_on < work.date_joining:
            errors["probation_passed_on"] = _(
                "Confirmation cannot be before the joining date."
            )
        elif (
            work.contract_end_date and work.probation_passed_on > work.contract_end_date
        ):
            errors["probation_passed_on"] = _(
                "Confirmation cannot be after the employment end date."
            )
    elif work.probation_passed_on:
        errors["probation_passed_on"] = _(
            "Use an actual confirmation date only when status is Confirmed passed."
        )
    if errors:
        raise ValidationError(errors)


def prepare_probation_save(work, update_fields=None):
    old = (
        type(work)
        ._base_manager.filter(pk=work.pk)
        .values(*FIELDS, "company_id")
        .first()
        if work.pk
        else None
    )
    if update_fields is not None and not set(FIELDS) & set(update_fields):
        return update_fields
    work.probation_status = work.probation_status or "not_recorded"
    changed = any(
        getattr(work, f)
        != (old[f] if old else ("not_recorded" if f == "probation_status" else None))
        for f in FIELDS
    )
    if not changed:
        return update_fields
    request = getattr(_thread_locals, "request", None)
    actor = getattr(work, "_probation_actor", None) or getattr(request, "user", None)
    imported = getattr(work, "_probation_from_onboarding", False)
    if actor and actor.is_authenticated and not imported:
        companies = {
            work.company_id_id,
            old["company_id"] if old else work.company_id_id,
        }
        if not all(can_manage_probation(actor, company_id) for company_id in companies):
            raise PermissionDenied(
                "Only the employee's company HR/Admin can manage probation."
            )
    work.probation_updated_at = timezone.now()
    work.probation_updated_by = actor if actor and actor.is_authenticated else None
    if actor and actor.is_authenticated:
        work._history_user = actor
    if update_fields is not None:
        update_fields = set(update_fields) | {
            "probation_updated_at",
            "probation_updated_by",
        }
    return update_fields


def annual_leave_eligible_on(employee, work_info=None):
    """Probation can bring access forward; it cannot postpone the statutory gate."""
    from leave.annual_entitlement import add_months

    work = work_info or getattr(employee, "employee_work_info", None)
    if not work or not work.date_joining:
        return None
    standard = add_months(work.date_joining, 3)
    if work.probation_status == "passed" and work.probation_passed_on:
        return min(standard, max(work.date_joining, work.probation_passed_on))
    if work.probation_status == "not_required":
        return work.date_joining
    return standard


def probation_date_expression(prefix=""):
    """Use the employee master after conversion, including an intentionally empty date."""
    from django.db.models import Case, When, F, DateField

    return Case(
        When(
            **{f"{prefix}converted_employee_id__isnull": False},
            then=F(f"{prefix}converted_employee_id__employee_work_info__probation_end"),
        ),
        default=F(f"{prefix}probation_end"),
        output_field=DateField(),
    )


def configure_form(form):
    request = getattr(_thread_locals, "request", None)
    work = form.instance
    company_id = work.company_id_id
    if not company_id and form.is_bound:
        raw = form.data.get(form.add_prefix("company_id"))
        company_id = int(raw) if raw and str(raw).isdigit() else None
    if not company_id and not work.pk and request:
        from base.auth_backends import get_write_company_id

        selected = getattr(request, "session", {}).get("selected_company")
        company_id = (
            int(selected)
            if selected and str(selected).isdigit()
            else get_write_company_id(request.user)
        )
    form.can_manage_probation = can_manage_probation(
        getattr(request, "user", None), company_id
    )
    for name in FIELDS:
        field = form.fields.get(name)
        if not field:
            continue
        field.required = False
        if name == "probation_status":
            field.choices = work.ProbationStatus.choices
        field.disabled = not form.can_manage_probation or (
            form.is_bound and form.add_prefix(name) not in form.data
        )
    form.probation_eligible_on = (
        annual_leave_eligible_on(work.employee_id) if work.employee_id_id else None
    )


def clean_form(form, cleaned):
    if not form.can_manage_probation:
        for name in FIELDS:
            key = form.add_prefix(name)
            current = getattr(form.instance, name)
            current = (
                current.isoformat() if hasattr(current, "isoformat") else current or ""
            )
            if key in form.data and str(form.data[key]) != str(current):
                form.add_error(name, _("Only company HR/Admin can change probation."))
    cleaned["probation_status"] = (
        cleaned.get("probation_status")
        or form.instance.probation_status
        or "not_recorded"
    )
    if cleaned["probation_status"] != "passed":
        cleaned["probation_passed_on"] = None
    company = cleaned.get("company_id")
    if (
        form.can_manage_probation
        and company
        and company.pk != form.instance.company_id_id
    ):
        actor = getattr(getattr(_thread_locals, "request", None), "user", None)
        if any(
            cleaned.get(f) != getattr(form.instance, f) for f in FIELDS
        ) and not can_manage_probation(actor, company.pk):
            form.add_error(
                "probation_status",
                _("HR/Admin access is required in the employee's new company."),
            )
    return cleaned


def copy_candidate_plan(candidate):
    """Copy a plan once at conversion; a planned end never means confirmation."""
    from employee.models import EmployeeWorkInformation

    if not candidate.converted_employee_id_id or not candidate.probation_end:
        return
    work = EmployeeWorkInformation._base_manager.filter(
        employee_id=candidate.converted_employee_id_id
    ).first()
    if (
        not work
        or work.probation_status != "not_recorded"
        or work.probation_end
        or work.probation_updated_at
    ):
        return
    if work.date_joining and candidate.probation_end < work.date_joining:
        return  # preserve the original candidate plan for HR review
    work.probation_end = candidate.probation_end
    work.probation_status = "on_probation"
    work._probation_from_onboarding = True
    work.save(update_fields=["probation_end", "probation_status"])
