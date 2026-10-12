from datetime import date
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from payroll.validation_messages import payroll_validation_message


class PayrollValidationMessageTests(SimpleTestCase):
    def test_employee_name_and_dictionary_errors_are_escaped(self):
        employee = SimpleNamespace(pk=2, get_full_name=lambda: '<img src=x onerror=alert(1)>')
        result = payroll_validation_message(employee, ValidationError({"residency_status": "Invalid <value>"}), date(2026, 9, 30))
        self.assertNotIn("<img", result)
        self.assertIn("&lt;value&gt;", result)

    def test_missing_profile_links_to_correct_employee_and_salary_month(self):
        employee = SimpleNamespace(pk=18, get_full_name=lambda: "Test Foreign Employee")
        result = payroll_validation_message(employee, ValidationError("Confirm declaration", code="missing_shg_profile"), date(2026, 9, 30))
        self.assertIn("/employee/employee-view-update/18/?tab=singapore", result)
        self.assertIn("salary_month=2026-09-01", result)
