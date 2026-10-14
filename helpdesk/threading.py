"""
threading.py

This module is used handle mail sent in thread
"""

import logging
from threading import Thread

from django.contrib import messages
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.utils.translation import gettext as _

from base.backends import ConfiguredEmailBackend
from base.models import Department
from employee.models import EmployeeWorkInformation
from helpdesk.models import Ticket

logger = logging.getLogger(__name__)


class TicketSendThread(Thread):
    """
    MailSend
    """

    def __init__(self, request, ticket, type):
        Thread.__init__(self)
        self.ticket = ticket
        self.type = type
        self.request = request
        self.assignees = ticket.assigned_to.all()
        self.host = request.get_host()
        self.protocol = "https" if request.is_secure() else "http"
        raised_on = ticket.get_raised_on_object()
        self.department_manager = None
        if isinstance(raised_on, Department):
            if raised_on.dept_manager.all():
                self.department_manager = raised_on.dept_manager.all().first().manager

    def send_email(self, subject, content, recipients, ticket_id="#"):
        host = self.host
        protocol = self.protocol
        link = "#"
        email_backend = ConfiguredEmailBackend()

        display_email_name = email_backend.dynamic_from_email_with_display_name
        reply_to = display_email_name
        if self.request:
            try:
                reply_to = self.request.user.employee_get.get_mail()
            except:
                logger.error(Exception)

        if ticket_id != "#":
            link = f"{protocol}://{host}/helpdesk/ticket-detail/{ticket_id}/"
        for recipient in recipients:
            html_message = render_to_string(
                "helpdesk/mail_templates/ticket_mail.html",
                {
                    "link": link,
                    "instance": recipient,
                    "host": host,
                    "protocol": protocol,
                    "subject": subject,
                    "content": content,
                },
                request=self.request,
            )

            email = EmailMessage(
                subject=f"Neutron HR | {subject}",
                body=html_message,
                from_email=display_email_name,
                to=[recipient.email],
                reply_to=[reply_to],
            )
            email.content_subtype = "html"
            try:
                email.send()
            except:
                messages.error(
                    self.request,
                    _("Mail not sent to %(employee)s")
                    % {"employee": recipient.get_full_name()},
                )

    def run(self) -> None:
        super().run()

        if self.type == "create":
            owner = self.ticket.employee_id
            manager = self.department_manager

            if manager:
                content_manager = f"{owner.get_full_name()} has raised a ticket for your department. Review the details and coordinate the next steps with the helpdesk team."
                subject_manager = "A new ticket needs your review"

                self.send_email(
                    subject_manager, content_manager, [manager], self.ticket.id
                )

            content_owner = "Your ticket has been submitted. The assigned team will review it. You can check its status and add updates in Neutron HR."
            subject_owner = "Your ticket is submitted"

            self.send_email(subject_owner, content_owner, [owner], self.ticket.id)

        elif self.type == "status_change":
            assignees = set(self.assignees or [])
            owner = self.ticket.employee_id
            manager = self.department_manager
            recipients = assignees | {x for x in [owner, manager] if x}

            tracking = self.ticket.tracking()
            updated_by = tracking[0]["updated_by"]
            new_status = tracking[0]["changes"][0]["new"]
            old_status = tracking[0]["changes"][0]["old"]

            subject = "Ticket status updated"
            content = f"{updated_by} updated this ticket from {old_status} to {new_status}. Open the ticket to view the latest details or add an update."

            self.send_email(subject, content, recipients, self.ticket.id)

        elif self.type == "delete":
            assignees = set(self.assignees or [])
            owner = self.ticket.employee_id
            manager = self.department_manager
            recipients = assignees | {x for x in [owner, manager] if x}

            subject = "Ticket deleted"
            content = f'The ticket "{self.ticket.title}" has been deleted. Contact the helpdesk team if you need further information.'

            self.send_email(subject, content, recipients)

        return


class AddAssigneeThread(Thread):
    """
    MailSend
    """

    def __init__(self, request, ticket, recipient):
        Thread.__init__(self)
        self.ticket = ticket
        self.recipients = recipient
        self.request = request
        self.host = request.get_host()
        self.protocol = "https" if request.is_secure() else "http"

    def run(self) -> None:
        super().run()

        content = "You are now assigned to this ticket. Review the details and coordinate the next steps with the requester or helpdesk team."
        subject = "A ticket has been assigned to you"

        host = self.host
        protocol = self.protocol
        email_backend = ConfiguredEmailBackend()
        display_email_name = email_backend.dynamic_from_email_with_display_name
        reply_to = display_email_name
        if self.request:
            try:
                reply_to = self.request.user.employee_get.get_mail()
            except:
                pass
        link = f"{protocol}://{host}/helpdesk/ticket-detail/{self.ticket.id}/"
        for recipient in self.recipients:
            html_message = render_to_string(
                "helpdesk/mail_templates/ticket_mail.html",
                {
                    "link": link,
                    "instance": recipient,
                    "host": host,
                    "protocol": protocol,
                    "subject": subject,
                    "content": content,
                },
                request=self.request,
            )

            email = EmailMessage(
                subject=f"Neutron HR | {subject}",
                body=html_message,
                from_email=display_email_name,
                to=[recipient.email],
                reply_to=[reply_to],
            )
            email.content_subtype = "html"
            try:
                email.send()
            except:
                messages.error(
                    self.request,
                    _("Mail not sent to %(employee)s")
                    % {"employee": recipient.get_full_name()},
                )


class RemoveAssigneeThread(Thread):
    """
    MailSend
    """

    def __init__(self, request, ticket, recipient):
        Thread.__init__(self)
        self.ticket = ticket
        self.recipients = recipient
        self.request = request
        self.host = request.get_host()
        self.protocol = "https" if request.is_secure() else "http"

    def run(self) -> None:
        super().run()

        content = "You are no longer assigned to this ticket. Open it if you need to check the latest status."
        subject = "Your ticket assignment has changed"
        email_backend = ConfiguredEmailBackend()

        display_email_name = email_backend.dynamic_from_email_with_display_name
        reply_to = display_email_name
        if self.request:
            try:
                reply_to = self.request.user.employee_get.get_mail()
            except:
                pass
        host = self.host
        protocol = self.protocol
        link = f"{protocol}://{host}/helpdesk/ticket-detail/{self.ticket.id}/"
        for recipient in self.recipients:
            html_message = render_to_string(
                "helpdesk/mail_templates/ticket_mail.html",
                {
                    "link": link,
                    "instance": recipient,
                    "host": host,
                    "protocol": protocol,
                    "subject": subject,
                    "content": content,
                },
                request=self.request,
            )

            email = EmailMessage(
                subject=f"Neutron HR | {subject}",
                body=html_message,
                from_email=display_email_name,
                to=[recipient.email],
                reply_to=[reply_to],
            )
            email.content_subtype = "html"
            try:
                email.send()
            except:
                messages.error(
                    self.request,
                    _("Mail not sent to %(employee)s")
                    % {"employee": recipient.get_full_name()},
                )
