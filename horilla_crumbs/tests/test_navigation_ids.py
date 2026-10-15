"""The breadcrumb processor must not store previous/next id lists on every request."""

from django.test import TestCase
from django.urls import reverse

from employee.models import Employee
from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user

NAV_KEYS = ("filtered_employees", "filtered_candidates")


class NavigationIdsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = make_company("Crumbs Co")
        cls.user = make_user("crumbs_admin", is_superuser=True)
        make_employee(
            company=cls.company, user=cls.user, email="crumbs_admin@example.com"
        )
        for i in range(3):
            make_employee(company=cls.company, email=f"crumbs{i}@example.com")

    def setUp(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["selected_company"] = str(self.company.pk)
        session.save()
        self.addCleanup(set_selected_company, None)

    def test_page_request_does_not_store_navigation_ids(self):
        for name in ("attendance-view", "recruitment-dashboard"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)
            for key in NAV_KEYS:
                self.assertNotIn(key, self.client.session, f"{name}: {key}")

    def _assert_leave_tab_neighbours(self, expected_ids):
        """Open the leave tab on the middle id; prev/next must come from expected_ids."""
        target = sorted(expected_ids)[1]
        response = self.client.get(reverse("leave-tab", args=[target]))
        self.assertEqual(response.status_code, 200)
        ordered = response.context["requests_ids"]
        self.assertEqual(sorted(ordered), sorted(expected_ids))
        index = ordered.index(target)
        previous = ordered[index - 1] if index > 0 else None
        following = ordered[index + 1] if index < len(ordered) - 1 else None
        self.assertEqual(response.context["previous"], previous)
        self.assertEqual(response.context["next"], following)

    def test_leave_tab_steps_through_all_employees_by_default(self):
        self._assert_leave_tab_neighbours(
            list(Employee.objects.values_list("id", flat=True))
        )

    def test_leave_tab_uses_ids_stored_by_list_view(self):
        ids = list(Employee.objects.values_list("id", flat=True))
        stored = ids[:1] + ids[2:]
        session = self.client.session
        session["filtered_employees"] = stored
        session.save()
        self._assert_leave_tab_neighbours(stored)
