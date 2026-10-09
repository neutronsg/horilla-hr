"""Absence-calendar privacy, tenant boundaries and lifecycle semantics."""

from datetime import date, datetime, timezone
from unittest.mock import patch

from django.contrib.auth.models import Group, Permission
from django.test import RequestFactory, TestCase, override_settings

from base.company_leave_calendar import company_leave_calendar, company_leave_detail
from base.models import CompanyGroupAssignment, CompanyLeaves, Department, Holidays
from horilla.horilla_middlewares import _thread_locals, set_selected_company
from horilla.testkit import make_company, make_employee
from leave.models import AvailableLeave, LeaveRequest, LeaveType


@override_settings(COMPANY_SCOPED_PERMISSIONS=True)
class CompanyLeaveCalendarTests(TestCase):
    def setUp(self):
        self.company = make_company("Calendar A")
        self.other = make_company("Calendar B")
        self.department = Department.objects.create(department="Engineering")
        self.employee = make_employee(company=self.company, email="calendar-staff@test.horilla", first_name="Alice", department=self.department)
        self.colleague = make_employee(company=self.company, email="calendar-colleague@test.horilla", first_name="Bob", department=self.department)
        self.outsider = make_employee(company=self.other, email="calendar-outsider@test.horilla", first_name="Private Other")
        self.kind = LeaveType.objects.create(name="Private medical leave", total_days=20, exclude_company_leave="yes", exclude_holiday="yes")
        for employee in (self.employee, self.colleague, self.outsider):
            AvailableLeave.objects.create(employee_id=employee, leave_type_id=self.kind, available_days=10)
        self.item = self.leave(self.colleague)
        self.leave(self.outsider)
        self.addCleanup(setattr, _thread_locals, "request", None)
        self.addCleanup(set_selected_company, None)

    def leave(self, employee, status="approved", start=date(2026, 10, 12), end=None, **values):
        item = LeaveRequest.objects.create(employee_id=employee, leave_type_id=self.kind, start_date=start, end_date=end or start, description="CONFIDENTIAL medical reason", **values)
        LeaveRequest._base_manager.filter(pk=item.pk).update(status=status, approved_available_days=item.requested_days if status in ("approved", "cancelled") else 0)
        item.refresh_from_db()
        return item

    def request(self, **query):
        values = {"start": "2026-10-01", "end": "2026-10-31"}
        values.update(query)
        http = RequestFactory().get("/ess/api/company-leave/", values)
        http.user = self.employee.employee_user_id
        http.session = {"selected_company": "all"}
        _thread_locals.request = http
        return http

    def data(self, **query):
        import json
        response = company_leave_calendar(self.request(**query))
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)

    def role(self, name="HR Manager", company=None, permissions=("view_leaverequest",)):
        group, _ = Group.objects.get_or_create(name=name)
        group.permissions.set(Permission.objects.filter(codename__in=permissions))
        CompanyGroupAssignment.objects.create(user=self.employee.employee_user_id, company=company or self.company, group=group)

    def test_employee_can_see_colleague_without_private_fields(self):
        data = self.data()
        self.assertEqual([row["name"] for row in data["events"]], [self.colleague.get_full_name()])
        self.assertEqual(set(data["events"][0]), {"id", "name", "department", "department_id", "start", "end", "days"})
        self.assertFalse(data["can_view_details"])
        self.assertNotIn("CONFIDENTIAL", str(data))
        self.assertNotIn(self.kind.name, str(data))

    def test_supplied_company_and_all_session_cannot_expand_scope(self):
        set_selected_company(str(self.other.pk))
        data = self.data(company=self.other.pk, employee_id=self.outsider.pk)
        self.assertEqual([row["id"] for row in data["events"]], [self.item.pk])

    def test_pending_rejected_and_inactive_leave_are_hidden(self):
        for status in ("requested", "rejected"):
            self.leave(self.colleague, status=status, start=date(2026, 10, 13))
        inactive = self.leave(self.colleague, start=date(2026, 10, 14))
        LeaveRequest._base_manager.filter(pk=inactive.pk).update(is_active=False)
        self.assertEqual([row["id"] for row in self.data()["events"]], [self.item.pk])

    def test_pending_cancellation_stays_until_final_refund(self):
        LeaveRequest._base_manager.filter(pk=self.item.pk).update(status="cancelled")
        self.assertEqual(len(self.data()["events"]), 1)
        LeaveRequest._base_manager.filter(pk=self.item.pk).update(status="rejected", approved_available_days=0)
        self.assertEqual(self.data()["events"], [])

    def test_ordinary_employee_cannot_fetch_details_by_id(self):
        response = company_leave_detail(self.request(), self.item.pk)
        self.assertEqual(response.status_code, 403)

    def test_hr_and_admin_with_existing_view_permission_can_fetch_details(self):
        import json
        for role in ("HR Manager", "Admin"):
            CompanyGroupAssignment.objects.filter(user=self.employee.employee_user_id).delete()
            self.role(role)
            self.assertTrue(self.data()["can_view_details"])
            response = company_leave_detail(self.request(), self.item.pk)
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.content)
            self.assertEqual(data["description"], "CONFIDENTIAL medical reason")
            self.assertEqual(data["available_days"], 10)

    def test_hr_without_view_permission_and_other_company_hr_cannot_fetch_details(self):
        self.role(permissions=("change_leaverequest",))
        self.role("Admin", company=self.other)
        self.assertEqual(company_leave_detail(self.request(), self.item.pk).status_code, 403)

    def test_hr_cannot_fetch_other_company_details(self):
        from django.http import Http404
        self.role()
        item = LeaveRequest._base_manager.get(employee_id=self.outsider)
        with self.assertRaises(Http404):
            company_leave_detail(self.request(), item.pk)

    def test_name_and_department_filters(self):
        self.assertEqual(len(self.data(q="bob")["events"]), 1)
        self.assertEqual(self.data(q="alice")["events"], [])
        self.assertEqual(len(self.data(department=str(self.department.pk))["events"]), 1)
        self.assertEqual(self.data(department="999999")["events"], [])

    def test_half_days_and_weekend_exclusions(self):
        rule = CompanyLeaves.objects.create(based_on_week_day="5", based_on_week=None)
        rule.company_id.add(self.company)
        item = self.leave(self.colleague, start=date(2026, 10, 16), end=date(2026, 10, 19), start_date_breakdown="second_half", end_date_breakdown="first_half")
        days = next(row["days"] for row in self.data()["events"] if row["id"] == item.pk)
        self.assertEqual(days, [{"date": "2026-10-16", "part": "second_half"}, {"date": "2026-10-18", "part": "full_day"}, {"date": "2026-10-19", "part": "first_half"}])
        self.assertIn("2026-10-17", self.data()["off_days"])

    def test_holiday_scoping_and_cross_year_range(self):
        Holidays.objects.create(name="Company holiday", start_date=date(2027, 1, 1), company_id=self.company)
        Holidays.objects.create(name="PRIVATE OTHER HOLIDAY", start_date=date(2026, 12, 31), company_id=self.other)
        item = self.leave(self.colleague, start=date(2026, 12, 31), end=date(2027, 1, 2))
        data = self.data(start="2026-12-28", end="2027-01-03")
        self.assertEqual(data["events"][0]["id"], item.pk)
        self.assertEqual([row["date"] for row in data["events"][0]["days"]], ["2026-12-31", "2027-01-02"])
        self.assertNotIn("PRIVATE OTHER", str(data))

    def test_invalid_and_excessive_ranges_rejected(self):
        for start, end in [("invalid", "2026-10-31"), ("2026-10-31", "2026-10-01"), ("2026-01-01", "2026-12-31")]:
            self.assertEqual(company_leave_calendar(self.request(start=start, end=end)).status_code, 400)

    def test_missing_company_denies_calendar(self):
        from employee.models import EmployeeWorkInformation
        EmployeeWorkInformation._base_manager.filter(employee_id=self.employee).update(company_id=None)
        self.employee.employee_user_id.refresh_from_db()
        self.assertEqual(company_leave_calendar(self.request()).status_code, 403)

    def test_today_uses_singapore_date_and_response_is_not_cached(self):
        with patch("base.company_leave_calendar.timezone.now", return_value=datetime(2026, 10, 9, 17, tzinfo=timezone.utc)):
            self.assertEqual(self.data()["today"], "2026-10-10")
        response = company_leave_calendar(self.request())
        self.assertIn("no-store", response["Cache-Control"])
