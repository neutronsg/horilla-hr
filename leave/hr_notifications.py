"""Passive HR notices sent only after the leave transaction commits."""

import logging
from threading import Thread

from django.core.mail import EmailMultiAlternatives
from django.db import close_old_connections
from django.template.loader import render_to_string
from notifications.signals import notify
from base.backends import ConfiguredEmailBackend
from base.models import DynamicEmailConfiguration
from leave.workflow import hr_observers, reporting_manager, company_id_for

logger = logging.getLogger(__name__)


class LeaveCompanyEmailBackend(ConfiguredEmailBackend):
    def __init__(self, company_id):
        self.leave_company_id = company_id
        super().__init__()

    def get_dynamic_email_config(self):
        return (
            DynamicEmailConfiguration._base_manager.filter(
                company_id=self.leave_company_id
            ).first()
            or DynamicEmailConfiguration._base_manager.filter(is_primary=True).first()
        )


class HRLeaveNoticeThread(Thread):
    def __init__(self, request, item, event):
        super().__init__(daemon=True)
        self.request, self.item, self.event = request, item, event

    def run(self):
        close_old_connections()
        try:
            self.send_notices()
        finally:
            close_old_connections()

    def send_notices(self):
        item = self.item
        manager = reporting_manager(item)
        actor = self.request.user.employee_get
        exclusions = {item.employee_id_id}
        if manager:
            exclusions.add(manager.pk)  # already gets the manager action/result path
        people = [p for p in hr_observers(item) if p.pk not in exclusions]
        owner = item.employee_id.get_full_name()
        if self.event == "submitted":
            subject = f"For your information: leave request from {owner}"
            content = f"{owner} has submitted a leave request. This is for your information; the reporting manager handles approval."
            if not manager:
                content = f"{owner} has submitted a leave request, but no active reporting manager is configured. Update the employee's Work Information to route the pending request to a manager."
        else:
            subject = f"For your information: leave request {item.status}"
            content = f"{owner}'s leave request is {item.status}. Updated by {actor.get_full_name()}. No approval action is needed from HR."
        backend = LeaveCompanyEmailBackend(company_id_for(item))
        sent_addresses = set()
        for person in people:
            try:
                notify.send(
                    actor,
                    recipient=person.employee_user_id,
                    verb=subject,
                    icon="people-circle",
                    redirect=f"/leave/request-view/?id={item.pk}",
                )
                address = person.get_mail()
                if not address or address.casefold() in sent_addresses:
                    continue
                sent_addresses.add(address.casefold())
                html = render_to_string(
                    "base/mail_templates/leave_request_template.html",
                    {
                        "instance": person,
                        "subject": subject,
                        "content": content,
                        "leave_request": item,
                        "link": item.pk,
                        "link_string": str(item.pk),
                        "host": self.request.get_host(),
                        "protocol": "https" if self.request.is_secure() else "http",
                    },
                )
                email = EmailMultiAlternatives(
                    f"Neutron HR | {subject}",
                    content,
                    backend.dynamic_from_email_with_display_name,
                    [address],
                    connection=backend,
                )
                email.attach_alternative(html, "text/html")
                if email.send() != 1:
                    raise RuntimeError("SMTP did not accept the HR notice")
            except Exception:
                logger.exception("HR leave notice failed for employee %s", person.pk)


def notify_new_manager(request, item):
    from leave.threading import LeaveMailSendThread

    manager = reporting_manager(item)
    if not manager:
        return
    notify.send(
        request.user.employee_get,
        recipient=manager.employee_user_id,
        verb="A pending leave request needs your approval.",
        icon="people-circle",
        redirect=f"/leave/request-view/?id={item.pk}",
    )
    LeaveMailSendThread(request, item, "manager_assigned").start()
