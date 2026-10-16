"""Ordered payslip navigation, revalidated against the list's access policy."""

import json
from uuid import uuid4

from django.core.cache import cache
from django.urls import reverse

from payroll.access import visible_payslips
from payroll.models.models import Payslip


def payslip_queryset(user):
    # The company manager applies the selected/allowed company scope, as in PayslipList.
    return visible_payslips(user, Payslip.objects.all()).order_by("-end_date", "-pk")


def remember_payslip_order(request, ids):
    token = uuid4().hex
    cache.set(f"payslip-navigation:{request.user.pk}:{token}", list(ids), 3600)
    return token


def payslip_navigation(request, payslip):
    queryset = payslip_queryset(request.user)
    token = request.GET.get("navigation", "")
    ids = cache.get(f"payslip-navigation:{request.user.pk}:{token}") if token else None
    if ids is None and "instance_ids" in request.GET:
        try:
            ids = json.loads(request.GET["instance_ids"])
            if not isinstance(ids, list):
                ids = None
        except (ValueError, TypeError):
            ids = None
    if ids is not None:
        # Treat both URL ids and cached ids as untrusted: permissions, release status
        # and company selection may have changed since the list was rendered.
        ids = list(
            dict.fromkeys(
                int(pk)
                for pk in ids
                if str(pk).isascii()
                and str(pk).isdecimal()
                and len(str(pk)) < 20
                and 0 < int(pk) < 2**63
            )
        )
        allowed = set(queryset.filter(pk__in=ids).values_list("pk", flat=True))
        ids = [pk for pk in ids if pk in allowed]
    if ids is None or payslip.pk not in ids:
        ids = list(queryset.values_list("pk", flat=True))
    token = remember_payslip_order(request, ids)
    position = ids.index(payslip.pk)

    def url(pk):
        return reverse("view-created-payslip", args=[pk]) + f"?navigation={token}"

    return {
        "payslip_position": position + 1,
        "payslip_count": len(ids),
        "previous_payslip_url": url(ids[position - 1]) if position else None,
        "next_payslip_url": url(ids[position + 1]) if position + 1 < len(ids) else None,
    }
