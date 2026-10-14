"""Small, company-scoped scheduled reminders with persisted attempt deduplication."""

import calendar
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.db import close_old_connections, transaction
from django.db.models import Q, Sum
from django.utils import timezone

from base.auth_backends import get_user_groups_for_company
from base.backends import ConfiguredEmailBackend
from base.models import DynamicEmailConfiguration
from employee.models import Employee
from payroll.hr_access import can_manage_claim_reminders
from payroll.hr_delivery_models import ClaimReminderDelivery, ClaimReminderPolicy

logger = logging.getLogger(__name__)


class CompanyReminderBackend(ConfiguredEmailBackend):
    def __init__(self, company_id):
        self.company_id = company_id
        super().__init__()
        self.timeout = 30
        self.fail_silently = False

    def get_dynamic_email_config(self):
        return (
            DynamicEmailConfiguration.objects.filter(
                company_id_id=self.company_id
            ).first()
            or DynamicEmailConfiguration.objects.filter(is_primary=True).first()
        )


def submission_cutoff(policy, now):
    """Find the cutoff whose reminder is today (including a next-month cutoff)."""
    for offset in (0, 1):
        month = now.month + offset
        year = now.year + (month > 12)
        month = (month - 1) % 12 + 1
        cutoff = date(
            year, month, min(policy.cutoff_day, calendar.monthrange(year, month)[1])
        )
        if cutoff - timedelta(days=policy.days_before) == now.date():
            return cutoff
    return None


def approval_recipients(policy):
    roles = ["HR Manager"] + (["Admin"] if policy.include_admin else [])
    candidates = (
        Employee.objects.entire()
        .filter(is_active=True, employee_user_id__is_active=True)
        .select_related("employee_user_id", "employee_work_info")
    )
    return [
        e
        for e in candidates
        if get_user_groups_for_company(e.employee_user_id, policy.company_id)
        .filter(name__in=roles)
        .exists()
        and can_manage_claim_reminders(e.employee_user_id, policy.company_id)
    ]


def deliver_once(policy, kind, cycle, employee, subject, body, html_body=None):
    # Reserve before SMTP. A crash after SMTP acceptance must not duplicate mail
    # when another worker polls. Failed/uncertain attempts remain visible to HR.
    with transaction.atomic():
        fresh = ClaimReminderPolicy.objects.select_for_update().get(pk=policy.pk)
        if not getattr(fresh, f"{kind}_enabled"):
            return None
        delivery, created = ClaimReminderDelivery.objects.get_or_create(
            policy=policy,
            kind=kind,
            cycle=cycle,
            employee=employee,
            defaults={"recipient": employee.get_mail() or ""},
        )
        if not created:
            return None
    if not delivery.recipient:
        delivery.status = "skipped"
        delivery.detail = "No email address configured."
    else:
        try:
            backend = CompanyReminderBackend(policy.company_id)
            email = EmailMultiAlternatives(
                subject,
                body,
                backend.dynamic_from_email_with_display_name,
                [delivery.recipient],
                connection=backend,
            )
            if html_body:
                email.attach_alternative(html_body, "text/html")
            if not email.send():
                raise RuntimeError("SMTP did not accept the reminder")
            delivery.status = "sent"
            delivery.detail = "SMTP accepted the email."
        except Exception:
            logger.exception(
                "Claim reminder %s failed for employee %s", kind, employee.pk
            )
            delivery.status = "failed"
            delivery.detail = "Check SMTP configuration and the recipient email."
    delivery.save(update_fields=("status", "detail"))
    return delivery


def run_due_claim_reminders(now=None):
    from payroll.models.models import Reimbursement

    now = now or timezone.now()
    results = []
    for policy in ClaimReminderPolicy.objects.filter(
        Q(submission_enabled=True) | Q(approval_enabled=True)
    ).select_related("company"):
        try:
            local = now.astimezone(ZoneInfo(policy.timezone))
            link = policy.base_url.rstrip("/") + "/payroll/view-reimbursement/"
            cutoff = submission_cutoff(policy, local)
            if (
                policy.submission_enabled
                and cutoff
                and local.time().replace(tzinfo=None) >= policy.submission_time
            ):
                employees = Employee.objects.entire().filter(
                    employee_work_info__company_id=policy.company_id,
                    is_active=True,
                    employee_user_id__is_active=True,
                )
                for employee in employees:
                    result = deliver_once(
                        policy,
                        "submission",
                        cutoff.strftime("%Y-%m"),
                        employee,
                        f"Neutron HR | Claim submission reminder — {cutoff:%d %b %Y}",
                        f"Hi {employee.get_full_name()},\n\nIf you have expenses to claim, submit them with receipts by {cutoff:%d %b %Y}. If you have no expenses, no action is needed. If you've already submitted a claim, check whether any other expenses remain.\n\nOpen your claims: {link}\n\nNeutron HR",
                        html_body=render_to_string(
                            "payroll/mail_templates/claim_reminder.html",
                            {
                                "kind": "submission",
                                "employee": employee,
                                "cutoff": cutoff,
                                "link": link,
                            },
                        ),
                    )
                    if result:
                        results.append(result)
            if (
                policy.approval_enabled
                and local.time().replace(tzinfo=None) >= policy.approval_time
            ):
                claims = Reimbursement.objects.entire().filter(
                    employee_id__employee_work_info__company_id=policy.company_id,
                    type="reimbursement",
                    status="requested",
                )
                count = claims.count()
                if count:
                    total = claims.aggregate(total=Sum("amount"))["total"] or 0
                    for employee in approval_recipients(policy):
                        result = deliver_once(
                            policy,
                            "approval",
                            local.date().isoformat(),
                            employee,
                            f"Neutron HR | {count} claims awaiting review",
                            f"Hi {employee.get_full_name()},\n\n{count} reimbursement claims are waiting for your review. Pending amount: S${total:,.2f}.\n\nReview the current list in Neutron HR: {link}\nThe count may change as claims are processed.\n\nNeutron HR",
                            html_body=render_to_string(
                                "payroll/mail_templates/claim_reminder.html",
                                {
                                    "kind": "approval",
                                    "employee": employee,
                                    "pending_count": count,
                                    "pending_amount": total,
                                    "link": link,
                                },
                            ),
                        )
                        if result:
                            results.append(result)
        except Exception:
            logger.exception("Claim reminder policy %s could not run", policy.pk)
    return results


def poll_claim_reminders():
    close_old_connections()
    try:
        return run_due_claim_reminders()
    finally:
        close_old_connections()
