"""
mail.py

This module is used handle mail sent in thread
"""

import logging
from threading import Thread

from django.core.mail import EmailMessage
from django.template.loader import render_to_string

from base.backends import ConfiguredEmailBackend
from django.db import close_old_connections
from horilla.horilla_middlewares import (
    _thread_locals,
    get_selected_company,
    set_selected_company,
)
from payroll.hr_access import can_email_payslip
from payroll.hr_delivery_models import PayslipEmailDelivery
from payroll.models.models import Payslip
from payroll.views.views import payslip_pdf

logger = logging.getLogger(__name__)


class MailSendThread(Thread):
    """
    MailSend
    """

    def __init__(self, request, result_dict, ids):
        Thread.__init__(self)
        self.result_dict = result_dict
        self.ids = ids
        self.request = request
        self.host = request.get_host()
        self.protocol = "https" if request.is_secure() else "http"
        self.company_context = get_selected_company()

    def run(self) -> None:
        previous_request = getattr(_thread_locals, "request", None)
        previous_company = get_selected_company()
        _thread_locals.request = self.request
        set_selected_company(self.company_context)
        close_old_connections()
        try:
            self.send_records()
        finally:
            _thread_locals.request = previous_request
            set_selected_company(previous_company)
            close_old_connections()

    def send_records(self):
        for record in list(self.result_dict.values()):
            delivery = record.get("delivery")
            try:
                self.send_record(record)
            except Exception:
                logger.exception(
                    "Payslip email failed for employee %s", record["employee_id"]
                )
                if delivery:
                    PayslipEmailDelivery.objects.filter(pk=delivery.pk).update(
                        status="failed",
                        detail="Email could not be sent. Check SMTP/PDF configuration before retrying.",
                    )

    def send_record(self, record):
        delivery = record.get("delivery")
        instances = list(
            Payslip.objects.filter(
                pk__in=[p.pk for p in record["instances"]]
            ).select_related("employee_id__employee_work_info")
        )
        if not instances or any(
            p.status not in ("confirmed", "paid")
            or not can_email_payslip(self.request.user, p)
            for p in instances
        ):
            raise ValueError("Payslip is no longer confirmed/paid or accessible")
        record["instances"] = instances
        html_message = render_to_string(
            "payroll/mail_templates/default.html",
            {
                "record": record,
                "host": self.host,
                "protocol": self.protocol,
            },
            request=self.request,
        )
        attachments = []
        for instance in record["instances"]:
            response = payslip_pdf(self.request, instance.id)
            if response.status_code != 200 or not response.content.startswith(b"%PDF"):
                raise ValueError("Payslip PDF generation failed")
            attachments.append(
                (
                    f"{instance.get_payslip_title()}.pdf",
                    response.content,
                    "application/pdf",
                )
            )
        employee = record["instances"][0].employee_id
        email_backend = ConfiguredEmailBackend()
        email_backend.fail_silently = False
        email_backend.timeout = 30
        display_email_name = email_backend.dynamic_from_email_with_display_name
        # The SMTP account's configured sender is verified by the mail provider.
        # The HR actor's personal email may not be an authorized From identity.
        reply_to = [self.request.user.employee_get.get_mail() or display_email_name]

        email = EmailMessage(
            f"Hello, {record['instances'][0].get_name()} Your Payslips is Ready!",
            html_message,
            display_email_name,
            [employee.get_mail()],
            reply_to=reply_to,
            connection=email_backend,
        )
        email.attachments = attachments

        # Send the email
        email.content_subtype = "html"
        if not email.send():
            raise RuntimeError("SMTP did not accept the email")
        Payslip.objects.filter(id__in=[p.pk for p in instances]).update(
            sent_to_employee=True
        )
        if delivery:
            PayslipEmailDelivery.objects.filter(pk=delivery.pk).update(
                status="sent", detail="SMTP accepted the email."
            )
