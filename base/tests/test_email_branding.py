from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.core.mail.backends.smtp import EmailBackend
from django.core.cache import cache
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase

from base.backends import ConfiguredEmailBackend
from base.email_branding import BRAND_MARKER, prepare_neutron_email
from base.models import DynamicEmailConfiguration
from horilla.horilla_middlewares import _thread_locals
from horilla.testkit import clear_selected_company


class NeutronEmailTests(TestCase):
    def setUp(self):
        _thread_locals.request = None
        clear_selected_company()

    def tearDown(self):
        _thread_locals.request = None
        clear_selected_company()
        super().tearDown()

    def test_mime_preserves_envelope_pdf_headers_and_plain_text(self):
        original = EmailMultiAlternatives(
            "Neutron HR | Payslip",
            "Private authored text https://hr.neutron.sg/",
            "Neutron <hr@neutron.sg>",
            ["zeyu+qa@neutron.sg"],
            cc=["zeyu+cc@neutron.sg"],
            bcc=["zeyu+bcc@neutron.sg"],
            reply_to=["zeyu+hr@neutron.sg"],
            headers={"X-QA": "preserved"},
        )
        original.attach("payslip.pdf", b"%PDF-private-bytes", "application/pdf")
        original.attach_alternative(
            "<html><body><p>Reviewed payslip</p></body></html>", "text/html"
        )
        branded = prepare_neutron_email(original)
        for field in (
            "subject",
            "body",
            "from_email",
            "to",
            "cc",
            "bcc",
            "reply_to",
            "extra_headers",
        ):
            self.assertEqual(getattr(branded, field), getattr(original, field))
        parts = list(branded.message().walk())
        self.assertEqual(
            next(
                p for p in parts if p.get_content_type() == "application/pdf"
            ).get_payload(decode=True),
            b"%PDF-private-bytes",
        )
        self.assertEqual(sum(p.get("Content-ID") == "<neutron_logo>" for p in parts), 1)
        self.assertIn(BRAND_MARKER, branded.alternatives[-1][0])
        repeated = prepare_neutron_email(branded)
        self.assertEqual(repeated.alternatives[-1][0].count(BRAND_MARKER), 1)
        self.assertEqual(
            sum(
                p.get("Content-ID") == "<neutron_logo>"
                for p in repeated.message().walk()
            ),
            1,
        )

    def test_plain_content_is_escaped_and_html_gets_readable_plain_links(self):
        plain = prepare_neutron_email(
            EmailMessage("Test", "<script>private & text</script>")
        )
        self.assertIn("&lt;script&gt;", plain.alternatives[-1][0])
        html = EmailMessage(
            "Action",
            '<p>Hello</p><a href="https://hr.neutron.sg/reset/token/">Reset</a>',
        )
        html.content_subtype = "html"
        self.assertIn(
            "Reset: https://hr.neutron.sg/reset/token/",
            prepare_neutron_email(html).body,
        )

    def test_missing_static_logo_keeps_readable_email(self):
        with patch("base.email_branding.finders.find", return_value=None):
            message = prepare_neutron_email(EmailMessage("Test", "Content"))
        self.assertNotIn("cid:neutron_logo", message.alternatives[-1][0])
        self.assertIn("Neutron", message.alternatives[-1][0])

    def test_transport_return_and_errors_are_not_changed(self):
        backend = ConfiguredEmailBackend()
        with patch.object(EmailBackend, "send_messages", return_value=0) as transport:
            self.assertEqual(backend.send_messages([EmailMessage("QA", "Text")]), 0)
            self.assertIn(
                BRAND_MARKER, transport.call_args.args[0][0].alternatives[-1][0]
            )
        with patch.object(
            EmailBackend, "send_messages", side_effect=RuntimeError("SMTP unavailable")
        ):
            with self.assertRaisesRegex(RuntimeError, "SMTP unavailable"):
                backend.send_messages([EmailMessage("QA", "Text")])

    def test_dynamic_name_uses_verified_sender_and_actor_reply_to(self):
        DynamicEmailConfiguration.objects.create(
            is_primary=True,
            from_email="hr@neutron.sg",
            display_name="Neutron HR",
            use_dynamic_display_name=True,
        )
        actor = SimpleNamespace(
            get_company=lambda: None,
            get_full_name=lambda: "HR User",
            get_email=lambda: "personal@example.com",
        )
        _thread_locals.request = SimpleNamespace(
            user=SimpleNamespace(
                pk=123,
                is_anonymous=False,
                is_authenticated=True,
                employee_get=actor,
            )
        )
        message = EmailMessage("QA", "Text")
        self.assertEqual(message.from_email, "HR User <hr@neutron.sg>")
        self.assertEqual(message.reply_to, ["HR User <personal@example.com>"])
        cache.delete_many(["reply_to123", "dynamic_display_name123"])

    def test_native_templates_render_correct_actions_without_legacy_placeholders(self):
        employee = SimpleNamespace(get_full_name=lambda: "QA <Employee>")
        slip = SimpleNamespace(
            get_name=lambda: "QA Employee",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
        )
        cases = [
            (
                "registration/password_reset_email_html.html",
                {
                    "uid": "qa-id",
                    "token": "qa-token",
                    "domain": "hr.neutron.sg",
                    "protocol": "https",
                },
                "/accounts/reset/qa-id/qa-token/",
            ),
            (
                "base/mail_templates/leave_request_template.html",
                {
                    "instance": employee,
                    "subject": "Leave request",
                    "content": "Review the request.",
                    "link": 42,
                    "link_string": "42",
                    "host": "hr.neutron.sg",
                    "protocol": "https",
                },
                "/leave/request-view/?id=42",
            ),
            (
                "payroll/mail_templates/default.html",
                {
                    "record": {"count": 1, "instances": [slip]},
                    "host": "hr.neutron.sg",
                    "protocol": "https",
                },
                "/payroll/view-payslip/",
            ),
            (
                "onboarding/mail_templates/default.html",
                {
                    "instance": SimpleNamespace(name="QA Candidate"),
                    "portal": "https://hr.neutron.sg/onboarding/user-creation/qa-token",
                },
                "/onboarding/user-creation/qa-token",
            ),
            (
                "helpdesk/mail_templates/ticket_mail.html",
                {
                    "instance": employee,
                    "subject": "Ticket assigned",
                    "content": "Review the ticket.",
                    "link": "https://hr.neutron.sg/helpdesk/ticket-detail/42/",
                },
                "/helpdesk/ticket-detail/42/",
            ),
            (
                "payroll/mail_templates/claim_reminder.html",
                {
                    "kind": "approval",
                    "employee": employee,
                    "pending_count": 1,
                    "pending_amount": 123.45,
                    "link": "https://hr.neutron.sg/payroll/view-reimbursement/",
                },
                "/payroll/view-reimbursement/",
            ),
        ]
        for name, context, action in cases:
            with self.subTest(name=name):
                html = render_to_string(name, context)
                self.assertIn(BRAND_MARKER, html)
                self.assertIn(action, html)
                self.assertNotIn("unsubscribe", html.lower())
                self.assertNotIn("Horilla", html)
                self.assertNotIn('href="#"', html)
        approval = render_to_string(
            "payroll/mail_templates/claim_reminder.html", cases[-1][1]
        )
        self.assertIn("1 reimbursement claim needs your review", approval)
        self.assertIn("QA &lt;Employee&gt;", approval)


class PlainTextAlternativeTests(SimpleTestCase):
    def test_blocks_keep_their_own_lines_and_hidden_preheaders_drop(self):
        from base.email_branding import html_to_plain

        plain = html_to_plain(
            '<div style="display:none">Preview text</div>'
            '<a href="https://neutron.sg/"><img alt="" src="cid:logo"></a>'
            "<p>Hi <strong>Alex</strong>,</p><p>Your leave was approved.</p>"
            '<p><a href="https://neutron.sg/">neutron.sg</a></p>'
        )
        self.assertEqual(
            plain, "Hi Alex,\n\nYour leave was approved.\n\nhttps://neutron.sg/"
        )
