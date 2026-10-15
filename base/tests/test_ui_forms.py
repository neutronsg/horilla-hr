"""Select placeholder presentation must not change posted values or explicit meanings."""

from django import forms
from django.test import SimpleTestCase

from base.models import Company


class SelectPlaceholderTests(SimpleTestCase):
    def test_blank_choices_are_readable_and_keep_their_values(self):
        class Example(forms.Form):
            leave_type = forms.ChoiceField(
                label="Leave type",
                choices=[("", "---------"), ("annual", "Annual leave")],
                required=False,
            )
            company = forms.ModelChoiceField(
                label="Company", queryset=Company.objects.none()
            )

        form = Example({"leave_type": "annual"})
        self.assertRegex(
            str(form["leave_type"]), r'<option value=""[^>]*>Select leave type</option>'
        )
        self.assertRegex(
            str(form["company"]), r'<option value=""[^>]*>Select company</option>'
        )
        self.assertEqual(form["leave_type"].value(), "annual")

    def test_explicit_defaults_and_required_choices_are_preserved(self):
        class Example(forms.Form):
            timezone = forms.ChoiceField(
                choices=[("", "System default"), ("utc", "UTC")]
            )
            company = forms.ModelChoiceField(
                queryset=Company.objects.none(), empty_label=None
            )

        form = Example()
        self.assertIn("System default", str(form["timezone"]))
        self.assertNotIn("Select company", str(form["company"]))

    def test_nullable_boolean_select_keeps_its_three_meanings(self):
        class Example(forms.Form):
            active = forms.NullBooleanField()

        html = str(Example()["active"])
        self.assertIn("Unknown", html)
        self.assertIn("Yes", html)
        self.assertIn("No", html)

    def test_filter_choice_iterator_keeps_one_readable_empty_option(self):
        from django_filters.fields import ChoiceField

        class Example(forms.Form):
            gender = ChoiceField(
                choices=[("female", "Female")], empty_label="---Choose Gender---"
            )

        html = str(Example()["gender"])
        self.assertNotIn("---Choose", html)
        self.assertEqual(html.count('value=""'), 1)
        self.assertIn("Select gender", html)
