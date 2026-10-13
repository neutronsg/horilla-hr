"""HR/Admin employee roles control Singapore access without extra permissions."""
from django.contrib.auth.models import AnonymousUser, Group, Permission
from django.test import RequestFactory, TestCase, override_settings

from base.models import CompanyGroupAssignment
from employee.singapore import can_access_singapore_details
from employee.tests.sg_access import grant_hr_employee_access
from horilla.testkit import make_company, make_employee


@override_settings(COMPANY_SCOPED_PERMISSIONS=True)
class SingaporeHRAccessTests(TestCase):
    def setUp(self):
        self.company = make_company("HR access tests")
        self.hr = make_employee(company=self.company, email="hr-access@test.example")
        self.employee = make_employee(company=self.company, email="staff-access@test.example")
        self.other_company = make_company("Other HR access tests")
        self.other = make_employee(company=self.other_company, email="other-access@test.example")

    def request(self, user=None):
        request = RequestFactory().get("/employee/")
        request.user = user if user is not None else self.hr.employee_user_id
        request.session = {"selected_company": "all"}
        return request

    def test_hr_and_admin_can_view_and_edit_self_and_staff_without_singapore_permissions(self):
        self.assertFalse(Permission.objects.filter(
            content_type__app_label="employee", content_type__model="singaporeemployeedetails",
        ).exists())
        for role in ("HR Manager", "Admin"):
            with self.subTest(role=role):
                self.hr.employee_user_id.company_group_assignments.all().delete()
                grant_hr_employee_access(self.hr, role=role)
                for employee in (self.hr, self.employee):
                    self.assertTrue(can_access_singapore_details(self.request(), employee))
                    self.assertTrue(can_access_singapore_details(self.request(), employee, edit=True))
                self.assertFalse(can_access_singapore_details(self.request(), self.other, edit=True))

    def test_direct_employee_permissions_do_not_replace_hr_role_in_target_company(self):
        grant_hr_employee_access(self.hr, company=self.other_company)
        self.hr.employee_user_id.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="employee", codename__in=("view_employee", "change_employee"),
        ))
        self.assertFalse(can_access_singapore_details(self.request(), self.employee))
        self.assertFalse(can_access_singapore_details(self.request(), self.employee, edit=True))
        self.assertTrue(can_access_singapore_details(self.request(), self.other, edit=True))

    def test_hr_role_and_employee_permissions_must_both_apply_to_target_company(self):
        # A role in this company may not borrow editing permissions from another.
        hr_group, _ = Group.objects.get_or_create(name="HR Manager")
        hr_group.permissions.clear()
        CompanyGroupAssignment.objects.create(user=self.hr.employee_user_id, group=hr_group, company=self.company)
        grant_hr_employee_access(self.hr, company=self.other_company, role="Admin")
        self.assertFalse(can_access_singapore_details(self.request(), self.employee, edit=True))
        self.assertTrue(can_access_singapore_details(self.request(), self.other, edit=True))

    def test_existing_employee_view_access_remains_read_only(self):
        grant_hr_employee_access(self.hr, view_only=True)
        self.assertTrue(can_access_singapore_details(self.request(), self.employee))
        self.assertFalse(can_access_singapore_details(self.request(), self.employee, edit=True))

    def test_change_employee_access_also_allows_hr_to_view_editor(self):
        grant_hr_employee_access(self.hr)
        self.hr.employee_user_id.company_group_assignments.get().group.permissions.set(
            Permission.objects.filter(content_type__app_label="employee", codename="change_employee")
        )
        self.assertTrue(can_access_singapore_details(self.request(), self.employee))
        self.assertTrue(can_access_singapore_details(self.request(), self.employee, edit=True))

    @override_settings(COMPANY_SCOPED_PERMISSIONS=False)
    def test_legacy_hr_group_uses_existing_employee_access_and_company_boundary(self):
        grant_hr_employee_access(self.hr)
        self.hr.employee_user_id.company_group_assignments.all().delete()
        self.assertTrue(can_access_singapore_details(self.request(), self.employee, edit=True))
        self.assertFalse(can_access_singapore_details(self.request(), self.other, edit=True))

    def test_inactive_and_anonymous_users_are_denied_and_superuser_can_access(self):
        grant_hr_employee_access(self.hr)
        self.assertFalse(can_access_singapore_details(self.request(AnonymousUser()), self.employee))
        user = self.hr.employee_user_id
        user.is_active = False
        self.assertFalse(can_access_singapore_details(self.request(), self.employee, edit=True))
        user.is_superuser = True
        self.assertFalse(can_access_singapore_details(self.request(), self.employee, edit=True))
        user.is_active = True
        self.assertTrue(can_access_singapore_details(self.request(), self.other, edit=True))

    def test_employee_without_company_is_denied(self):
        grant_hr_employee_access(self.hr)
        self.employee.employee_work_info.company_id = None
        self.assertFalse(can_access_singapore_details(self.request(), self.employee, edit=True))
