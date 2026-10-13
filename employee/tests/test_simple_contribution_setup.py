from datetime import date
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from employee.contributions import ContributionProfileForm
from employee.singapore_models import SingaporeContributionProfile, SingaporeEmployeeDetails
from horilla.testkit import make_company, make_employee
from payroll.models.models import Contract
from payroll.shg import calculate_shg, profile_for


class SimpleContributionSetupTests(TestCase):
    def setUp(self):
        self.employee = make_employee(company=make_company("Simple funds", country="Singapore"), email="simple-funds@example.test")
        self.details = SingaporeEmployeeDetails.objects.create(employee=self.employee, residency_status="foreigner", work_pass_type="S_PASS")
        self.contract = Contract.objects.filter(employee_id=self.employee).first()

    def save_setup(self, month=date(2026, 10, 13), **changes):
        data = {"configuration_version": "funds-v3"}
        data.update({f"{fund}_mode": "not_applicable" for fund in ("cdac", "ecf", "sinda", "mbmf")})
        data.update(changes)
        previous = SingaporeContributionProfile.objects.filter(employee=self.employee).order_by("-created_at", "-pk").first()
        form = ContributionProfileForm(data, details=self.details, previous=previous,
            instance=SingaporeContributionProfile(employee=self.employee))
        with patch("employee.contributions.timezone.localdate", return_value=month):
            self.assertTrue(form.is_valid(), form.errors)
            return form.save()

    def test_no_month_or_note_needed_and_first_setup_covers_new_past_and_future_payroll(self):
        setup = self.save_setup()
        self.assertTrue(setup.is_baseline)
        self.assertEqual(setup.effective_month, date(2026, 10, 1))
        for month in (date(2026, 9, 1), date(2026, 10, 1), date(2027, 1, 1)):
            self.assertEqual(profile_for(self.employee, month), setup)
        result = calculate_shg(self.employee, self.contract, date(2026, 9, 1), date(2026, 9, 30), 4000, [])
        self.assertEqual(result["total"], 0)

    def test_later_normal_change_keeps_earlier_settings_and_carries_forward(self):
        first = self.save_setup()
        later = self.save_setup(month=date(2026, 12, 2), mbmf_mode="auto")
        self.assertFalse(later.is_baseline)
        self.assertEqual(profile_for(self.employee, date(2026, 9, 1)), first)
        self.assertEqual(profile_for(self.employee, date(2026, 11, 1)), first)
        self.assertEqual(profile_for(self.employee, date(2027, 1, 1)), later)

    def test_specific_month_preserves_dated_history_and_does_not_create_baseline(self):
        dated = self.save_setup(use_start_month="on", start_month="2026-09")
        self.assertFalse(dated.is_baseline)
        self.assertIsNone(profile_for(self.employee, date(2026, 8, 1)))
        self.assertEqual(profile_for(self.employee, date(2026, 9, 1)), dated)

    def test_first_normal_setup_does_not_replace_existing_older_dated_declaration(self):
        old = self.save_setup(use_start_month="on", start_month="2026-09", mbmf_mode="auto")
        baseline = self.save_setup()
        self.assertEqual(profile_for(self.employee, date(2026, 8, 1)), baseline)
        self.assertEqual(profile_for(self.employee, date(2026, 9, 1)), old)

    def test_missing_specific_month_is_an_error_and_stale_forms_require_reload(self):
        for changes in ({"use_start_month": "on"}, {"configuration_version": "funds-v2"}):
            data = {"configuration_version": "funds-v3", **{f"{fund}_mode": "not_applicable" for fund in ("cdac", "ecf", "sinda", "mbmf")}, **changes}
            form = ContributionProfileForm(data, details=self.details, instance=SingaporeContributionProfile(employee=self.employee))
            self.assertFalse(form.is_valid())

    def test_baseline_does_not_guess_pre_pr_contribution_history(self):
        self.details.residency_status = "pr"
        self.details.work_pass_type = ""
        self.details.pr_effective_date = date(2026, 10, 1)
        self.details.save()
        self.save_setup()
        with self.assertRaisesMessage(ValidationError, "before the employee's PR change"):
            calculate_shg(self.employee, self.contract, date(2026, 9, 1), date(2026, 9, 30), 4000, [])
