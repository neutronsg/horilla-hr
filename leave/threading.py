import logging
from threading import Thread

from django.contrib import messages
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils.translation import gettext as _

from base.backends import ConfiguredEmailBackend

logger = logging.getLogger(__name__)


class LeaveMailSendThread(Thread):

    def __init__(self, request, leave_request, type):
        Thread.__init__(self)
        self.request = request
        self.leave_request = leave_request
        self.type = type
        self.host = request.get_host()
        self.protocol = "https" if request.is_secure() else "http"

    def send_email(self, subject, content, recipients, leave_request_id="#"):
        email_backend = ConfiguredEmailBackend()
        display_email_name = email_backend.dynamic_from_email_with_display_name

        host = self.host
        protocol = self.protocol

        link = None
        if leave_request_id != "#":
            link = int(leave_request_id)

        for recipient in recipients:
            if not recipient:
                continue

            html_message = render_to_string(
                "base/mail_templates/leave_request_template.html",
                {
                    "link": link,
                    "link_string": str(link) if link else "",
                    "leave_request": self.leave_request,
                    "instance": recipient,
                    "host": host,
                    "protocol": protocol,
                    "subject": subject,
                    "content": content,
                },
                request=self.request,
            )

            email = EmailMultiAlternatives(
                subject=f"Neutron HR | {subject}",
                body=html_message,
                from_email=display_email_name,
                to=[recipient.get_mail()],
                reply_to=[display_email_name],
            )

            email.attach_alternative(html_message, "text/html")

            email.send()

    def run(self) -> None:
        super().run()
        if self.type == "request":
            owner = self.leave_request.employee_id
            reporting_manager = self.leave_request.employee_id.get_reporting_manager()

            content_manager = f"{owner.get_full_name()} has submitted a leave request. Review the dates and leave details, then approve or reject the request in Neutron HR."
            subject_manager = f"Leave request from {owner.get_full_name()}"

            self.send_email(
                subject_manager,
                content_manager,
                [reporting_manager],
                self.leave_request.id,
            )

            content_owner = "Your leave request has been submitted and is awaiting review. You can check its status in Neutron HR. Contact your reporting manager or HR team if you need help."
            subject_owner = "Your leave request is submitted"

            self.send_email(
                subject_owner, content_owner, [owner], self.leave_request.id
            )

        elif self.type == "approve":
            owner = self.leave_request.employee_id
            reporting_manager = self.leave_request.employee_id.get_reporting_manager()

            subject = "Your leave request is approved"
            content = "Your leave request has been approved. View the confirmed dates and details in Neutron HR."

            self.send_email(subject, content, [owner], self.leave_request.id)

        elif self.type == "reject":
            owner = self.leave_request.employee_id
            reporting_manager = self.leave_request.employee_id.get_reporting_manager()

            subject = "Your leave request was not approved"
            content = "Your leave request was not approved. View the request in Neutron HR and contact your reporting manager or HR team to discuss the next steps."

            self.send_email(subject, content, [owner], self.leave_request.id)

        elif self.type == "cancel":
            owner = self.leave_request.employee_id
            reporting_manager = self.leave_request.employee_id.get_reporting_manager()

            content_manager = f"{owner.get_full_name()} has requested to cancel their leave. Review the request in Neutron HR before confirming the cancellation."
            subject_manager = "Leave cancellation needs review"

            self.send_email(
                subject_manager,
                content_manager,
                [reporting_manager],
                self.leave_request.id,
            )

            content_owner = "Your leave cancellation request has been submitted and is awaiting review. Check the request in Neutron HR for the latest status."
            subject_owner = "Your cancellation request is submitted"

            self.send_email(
                subject_owner, content_owner, [owner], self.leave_request.id
            )

        return


class LeaveClashThread(Thread):

    def __init__(self, leave_request):
        Thread.__init__(self)
        self.leave_request = leave_request

    def count_leave_clashes(self):
        from leave.models import LeaveRequest

        """
        Method to count leave clashes where this employee's leave request overlaps
        with other employees' requested dates.
        """
        overlapping_requests = LeaveRequest.objects.exclude(
            id=self.leave_request.id
        ).filter(
            Q(
                employee_id__employee_work_info__department_id=self.leave_request.employee_id.employee_work_info.department_id
            )
            | Q(
                employee_id__employee_work_info__job_position_id=self.leave_request.employee_id.employee_work_info.job_position_id
            ),
            start_date__lte=self.leave_request.end_date,
            end_date__gte=self.leave_request.start_date,
        )

        return overlapping_requests.count()

    def run(self) -> None:
        from leave.models import LeaveRequest

        super().run()
        dates = self.leave_request.requested_dates()
        leave_requests_to_update = LeaveRequest.objects.filter(
            Q(start_date__in=dates) | Q(end_date__in=dates)
        )

        for leave_request in leave_requests_to_update:
            leave_request.leave_clashes_count = self.count_leave_clashes()
            leave_request.save()
