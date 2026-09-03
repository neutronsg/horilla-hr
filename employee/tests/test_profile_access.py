from django.contrib.auth.models import Permission
from django.test import RequestFactory, TestCase

from employee.models import Employee
from employee.views import can_view_employee_profile, visible_employee_queryset
from horilla.testkit import make_company, make_employee


class EmployeeProfileAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        company = make_company("Profile Access Co")
        cls.viewer = make_employee(
            company=company,
            email="viewer@profile.test",
            first_name="Viewer",
        )
        cls.peer = make_employee(
            company=company,
            email="peer@profile.test",
            first_name="Peer",
        )
        cls.report = make_employee(
            company=company,
            email="report@profile.test",
            first_name="Report",
        )
        cls.report.employee_work_info.reporting_manager_id = cls.viewer
        cls.report.employee_work_info.save(update_fields=["reporting_manager_id"])

    def request_for(self, employee):
        request = RequestFactory().get("/")
        request.user = employee.employee_user_id
        return request

    def test_employee_can_view_own_profile(self):
        self.assertTrue(can_view_employee_profile(self.request_for(self.viewer), self.viewer))

    def test_employee_cannot_view_peer_profile(self):
        self.assertFalse(can_view_employee_profile(self.request_for(self.viewer), self.peer))

    def test_manager_can_view_direct_report(self):
        self.assertTrue(can_view_employee_profile(self.request_for(self.viewer), self.report))

    def test_view_employee_permission_allows_profile(self):
        user = self.viewer.employee_user_id
        user.user_permissions.add(Permission.objects.get(codename="view_employee"))
        self.assertTrue(can_view_employee_profile(self.request_for(self.viewer), self.peer))

    def test_directory_hides_peer_but_includes_self_and_direct_report(self):
        visible = visible_employee_queryset(
            self.request_for(self.viewer), Employee.objects.all()
        )
        self.assertSetEqual(
            set(visible.values_list("pk", flat=True)),
            {self.viewer.pk, self.report.pk},
        )
