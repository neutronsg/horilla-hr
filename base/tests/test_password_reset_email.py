from django.template.loader import render_to_string
from django.test import SimpleTestCase


class PasswordResetEmailTemplateTests(SimpleTestCase):
    def test_email_contains_reset_link_without_repeating_username(self):
        body = render_to_string(
            "registration/password_reset_email.html",
            {
                "site_name": "hr.neutron.sg",
                "protocol": "https",
                "domain": "hr.neutron.sg",
                "uid": "encoded-user-id",
                "token": "reset-token",
                "user": type(
                    "User",
                    (),
                    {
                        "username": "personal@example.com",
                        "get_username": lambda self: self.username,
                    },
                )(),
            },
        )

        self.assertIn(
            "https://hr.neutron.sg/accounts/reset/encoded-user-id/reset-token/",
            body,
        )
        self.assertNotIn("personal@example.com", body)
        self.assertNotIn("in case you", body.lower())
