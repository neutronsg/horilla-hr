"""Viewing settings must not change a user's records-per-page preference."""

from django.test import TestCase
from django.urls import reverse

from base.models import DynamicPagination
from horilla.testkit import make_company, make_employee, make_user


class PaginationPreferenceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = make_company("Pagination Co")
        cls.user = make_user("pagination_admin", is_superuser=True)
        make_employee(company=cls.company, user=cls.user, email="pagination_admin@example.com")

    def setUp(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["selected_company"] = str(self.company.pk)
        session.save()

    def test_viewing_system_preferences_creates_no_preference(self):
        response = self.client.get(reverse("system-preferences-view"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(DynamicPagination.objects.filter(user_id=self.user).exists())

    def test_first_save_creates_preference(self):
        self.client.post(
            reverse("pagination-settings-view"),
            {"setting_id": "", "company_id": str(self.company.pk), "pagination": "30"},
            HTTP_HX_REQUEST="true",
        )
        setting = DynamicPagination.objects.get(user_id=self.user, company_id=self.company)
        self.assertEqual(setting.pagination, 30)

    def test_existing_preference_is_updated(self):
        self.client.post(
            reverse("pagination-settings-view"),
            {"setting_id": "", "company_id": str(self.company.pk), "pagination": "15"},
            HTTP_HX_REQUEST="true",
        )
        setting = DynamicPagination.objects.get(user_id=self.user, company_id=self.company)
        self.client.post(
            reverse("pagination-settings-view"),
            {"setting_id": str(setting.pk), "pagination": "40"},
            HTTP_HX_REQUEST="true",
        )
        setting.refresh_from_db()
        self.assertEqual(setting.pagination, 40)
        self.assertEqual(DynamicPagination.objects.filter(user_id=self.user).count(), 1)
