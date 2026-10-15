"""Personal dashboard address, attendance-aware dashboards and sidebar sections."""

from django.template import Context, Template
from django.test import RequestFactory, TestCase
from django.urls import reverse

from attendance.models import AttendanceGeneralSetting
from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user


class NeutronHomeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = make_company("Home Co")
        cls.admin = make_user("home_admin", is_superuser=True)
        make_employee(company=cls.company, user=cls.admin, email="home_admin@example.com")
        cls.staff = make_user("home_staff")
        make_employee(company=cls.company, user=cls.staff, email="home_staff@example.com")

    def setUp(self):
        self.addCleanup(set_selected_company, None)

    def sign_in(self, user):
        self.client.force_login(user)
        session = self.client.session
        session["selected_company"] = str(self.company.pk)
        session.save()

    def set_check_in(self, enabled):
        AttendanceGeneralSetting.objects.update_or_create(
            company_id=self.company, defaults={"enable_check_in": enabled}
        )

    def test_personal_dashboard_lives_at_my_and_ess_redirects(self):
        self.assertEqual(reverse("ess-dashboard"), "/my/")
        self.sign_in(self.staff)
        response = self.client.get("/ess/?month=10")
        self.assertRedirects(response, "/my/?month=10", fetch_redirect_response=False)

    def test_overview_hides_attendance_when_check_in_is_off(self):
        self.sign_in(self.admin)
        self.set_check_in(False)
        response = self.client.get(reverse("dashboard"))
        self.assertFalse(response.context["attendance_tracking"])
        self.assertNotContains(response, 'data-chart-id="attendance_overview"')

    def test_overview_shows_attendance_when_check_in_is_on(self):
        self.sign_in(self.admin)
        self.set_check_in(True)
        response = self.client.get(reverse("dashboard"))
        self.assertTrue(response.context["attendance_tracking"])
        self.assertContains(response, 'data-chart-id="attendance_overview"')

    def _nav_apps(self, check_in):
        self.set_check_in(check_in)
        request = RequestFactory().get("/")
        request.user = self.admin
        request.session = {"selected_company": str(self.company.pk)}
        menus = [{"app": "employee", "menu": "Employee"}, {"app": "attendance", "menu": "Attendance"}, {"app": "leave", "menu": "Leave"}]
        template = Template(
            "{% load neutron_ui %}{% neutron_nav_groups menus as groups %}"
            "{% for label, items in groups %}{% for m in items %}{{ m.app }},{% endfor %}{% endfor %}"
        )
        return template.render(Context({"request": request, "menus": menus})).strip(",").split(",")

    def test_sidebar_drops_attendance_section_without_check_in(self):
        self.assertNotIn("attendance", self._nav_apps(False))
        self.assertIn("attendance", self._nav_apps(True))

    def test_dashboard_link_points_employees_to_their_dashboard(self):
        request = RequestFactory().get("/")
        request.user = self.staff
        request.session = {}
        html = Template("{% load neutron_ui %}{% neutron_home_url %}").render(Context({"request": request}))
        self.assertEqual(html, "/my/")
