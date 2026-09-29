"""Draft payroll does not treat unworked future days as absences."""

from datetime import date, timedelta

from django.test import TestCase

from attendance.views.summary import build_monthly_summary
from horilla.testkit import make_company, make_employee
from employee.models import Employee


class FuturePayrollSummaryTests(TestCase):
    def test_future_working_day_is_expected_attendance_for_draft(self):
        company = make_company("Future Attendance")
        employee = make_employee(company=company, email="future@attendance.test")
        future_day = date.today() + timedelta(days=1)
        while future_day.weekday() >= 5:
            future_day += timedelta(days=1)
        employees = Employee.objects.filter(pk=employee.pk)

        regular, _, _ = build_monthly_summary(future_day, future_day, employees)
        projected, _, _ = build_monthly_summary(
            future_day, future_day, employees, assume_future_present=True
        )

        self.assertEqual(regular[0]["absent"], 1)
        self.assertEqual(projected[0]["absent"], 0)
        self.assertEqual(projected[0]["present"], 1)
