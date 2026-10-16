"""One audience and permission boundary for shared company documents."""

from django.db.models import Q

from base.auth_backends import (
    get_allowed_company_ids,
    get_effective_permission_codenames,
    get_user_groups_for_company,
)
from base.models import Company
from employee.models import Policy


def employee_company_id(user):
    if not user.is_authenticated or not user.is_active:
        return None
    employee = getattr(user, "employee_get", None)
    if not employee or not employee.is_active:
        return None
    return getattr(getattr(employee, "employee_work_info", None), "company_id_id", None)


def can_manage_company(user, company_id, action="view"):
    if not user.is_authenticated or not user.is_active or not company_id:
        return False
    if user.is_superuser:
        return True
    if company_id not in get_allowed_company_ids(user):
        return False
    if (
        not get_user_groups_for_company(user, company_id)
        .filter(name__in=("HR Manager", "Admin"))
        .exists()
    ):
        return False
    permissions = set(get_effective_permission_codenames(user, company_id))
    if action == "view":
        return bool(permissions & {"view_policy", "change_policy", "delete_policy"})
    return f"{action}_policy" in permissions


def manageable_companies(user, action="view"):
    if not user.is_authenticated or not user.is_active:
        return Company.objects.none()
    companies = Company.objects.all().order_by("company")
    if user.is_superuser:
        return companies
    return companies.filter(
        pk__in=[
            pk
            for pk in get_allowed_company_ids(user)
            if can_manage_company(user, pk, action)
        ]
    )


def can_manage_document(user, document, action="view"):
    if not user.is_authenticated or not user.is_active:
        return False
    # Legacy unscoped records are available only to the administrator for mapping.
    companies = list(document.company_id.all())
    if not companies:
        return user.is_superuser
    return all(can_manage_company(user, company.pk, action) for company in companies)


def published_documents(user):
    company_id = employee_company_id(user)
    if company_id is None:
        return Policy.objects.entire().none()
    return (
        Policy.objects.entire()
        .filter(company_id=company_id, is_active=True, is_visible_to_all=True)
        .distinct()
        .prefetch_related("attachments", "company_id")
        .order_by("-pinned", "-published_at", "-pk")
    )


def visible_documents(user):
    """Management grants apply in their own company, never the session union."""
    if not user.is_authenticated or not user.is_active:
        return Policy.objects.entire().none()
    queryset = Policy.objects.entire()
    if not user.is_superuser:
        employee_company = employee_company_id(user)
        query = Q(company_id__in=manageable_companies(user))
        if employee_company:
            query |= Q(
                company_id=employee_company, is_active=True, is_visible_to_all=True
            )
        queryset = queryset.filter(query)
    return (
        queryset.distinct()
        .prefetch_related("attachments", "company_id")
        .order_by("-pinned", "-published_at", "-pk")
    )


def can_read_document(user, document):
    if can_manage_document(user, document):
        return True
    # HR may read a multi-company record in their own management scope, but
    # changing it still requires authority in every affected company.
    if any(
        can_manage_company(user, company.pk) for company in document.company_id.all()
    ):
        return True
    return bool(
        document.is_active
        and document.is_visible_to_all
        and employee_company_id(user)
        in {company.pk for company in document.company_id.all()}
    )
