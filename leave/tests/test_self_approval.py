"""Normal self-approval is forbidden; administrator exceptions are explicit."""

from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import Group, Permission
from django.test import Client, RequestFactory, TestCase, override_settings
from django.contrib.messages.storage.fallback import FallbackStorage
from rest_framework.test import APIRequestFactory, force_authenticate

from base.models import CompanyGroupAssignment
from horilla.horilla_middlewares import _thread_locals, set_selected_company
from horilla.testkit import make_company, make_employee
from leave.models import (
    AvailableLeave,
    LeaveRequest,
    LeaveRequestConditionApproval,
    LeaveType,
)
from leave.services import can_approve_own_leave


@override_settings(COMPANY_SCOPED_PERMISSIONS=True)
class SelfApprovalTests(TestCase):
    def setUp(self):
        self.company = make_company("Self approval company")
        self.other = make_company("Other self approval company")
        self.employee = make_employee(
            company=self.company, email="self-approve@test.horilla"
        )
        self.manager = make_employee(
            company=self.company, email="second-approve@test.horilla"
        )
        self.user = self.employee.employee_user_id
        self.user.is_new_employee = False
        self.user.save()
        self.manager.employee_user_id.is_new_employee = False
        self.manager.employee_user_id.save()
        self.kind = LeaveType.objects.create(name="Self approval annual", total_days=20)
        self.balance = AvailableLeave.objects.create(
            employee_id=self.employee, leave_type_id=self.kind, available_days=10
        )
        self.item = LeaveRequest.objects.create(
            employee_id=self.employee,
            leave_type_id=self.kind,
            start_date=date(2026, 10, 19),
            end_date=date(2026, 10, 19),
            description="QA self approval",
        )
        self.addCleanup(setattr, _thread_locals, "request", None)
        self.addCleanup(set_selected_company, None)

    def role(
        self,
        name="HR Manager",
        company=None,
        permissions=("change_leaverequest", "view_leaverequest"),
        user=None,
    ):
        group, _ = Group.objects.get_or_create(name=name)
        group.permissions.set(Permission.objects.filter(codename__in=permissions))
        CompanyGroupAssignment.objects.create(
            user=user or self.user, company=company or self.company, group=group
        )

    def client_as(self, user=None):
        client = Client()
        client.force_login(
            user or self.user, backend="base.auth_backends.CompanyScopedBackend"
        )
        session = client.session
        session["selected_company"] = str(self.company.pk)
        session.save()
        return client

    def api_request(self, bulk=False, user=None):
        http = APIRequestFactory().put(
            "/api/leave/approve/",
            {"leave_request_id": [self.item.pk]} if bulk else {},
            format="multipart",
        )
        actor = user or self.user
        force_authenticate(http, user=actor)
        context = RequestFactory().get("/")
        context.user = actor
        context.session = {"selected_company": str(self.company.pk)}
        _thread_locals.request = context
        set_selected_company(str(self.company.pk))
        return http

    def assert_pending(self):
        self.item.refresh_from_db()
        self.balance.refresh_from_db()
        self.assertEqual(
            (self.item.status, self.balance.available_days), ("requested", 10)
        )
        self.assertEqual(self.item.leaverequestcomment_set.count(), 0)

    def test_hr_and_admin_cannot_self_approve_normally(self):
        for name in ("HR Manager", "Admin"):
            CompanyGroupAssignment.objects.filter(user=self.user).delete()
            self.role(name)
            self.assertFalse(can_approve_own_leave(self.user, self.item))
            response = self.client_as().get(
                f"/leave/request-approve/{self.item.pk}/", HTTP_HX_REQUEST="true"
            )
            self.assertEqual(response.status_code, 403)
            self.assert_pending()

    def test_api_single_denies_admin_self_approval(self):
        from horilla_api.api_views.leave.views import LeaveRequestApproveAPIView

        self.role("Admin")
        response = LeaveRequestApproveAPIView.as_view()(
            self.api_request(), pk=self.item.pk
        )
        self.assertEqual(response.status_code, 403)
        self.assert_pending()

    def test_api_bulk_skips_hr_self_approval(self):
        from horilla_api.api_views.leave.views import (
            LeaveRequestBulkApproveDeleteAPIview,
        )

        self.role()
        response = LeaveRequestBulkApproveDeleteAPIview.as_view()(
            self.api_request(bulk=True)
        )
        self.assertEqual(response.status_code, 200)
        self.assert_pending()

    def test_web_bulk_skips_admin_self_approval(self):
        self.role("Admin")
        response = self.client_as().post(
            "/leave/leave-requests-bulk-approve/",
            {"ids": [self.item.pk]},
            HTTP_HX_REQUEST="true",
        )
        self.assertLess(response.status_code, 400)
        self.assert_pending()

    def test_cbv_bulk_skips_hr_self_approval(self):
        from leave.cbv.leave_requests import LeaveRequestsListView

        self.role()
        http = RequestFactory().post(
            "/leave/request-filter/",
            {"instance_ids": [self.item.pk], "status": "approved"},
            HTTP_HX_REQUEST="true",
        )
        http.user = self.user
        http.session = {"selected_company": str(self.company.pk)}
        http._messages = FallbackStorage(http)
        _thread_locals.request = http
        set_selected_company(str(self.company.pk))
        LeaveRequestsListView.handle_bulk_submission(None, http)
        self.assert_pending()

    def test_explicit_admin_exception_needs_reason_even_for_own_leave(self):
        self.role("Admin")
        c = self.client_as()
        url = f"/leave/admin-intervention/{self.item.pk}/"
        c.post(url, {"decision": "approve", "reason": ""}, HTTP_HX_REQUEST="true")
        self.assert_pending()
        with patch("leave.views.LeaveMailSendThread.start"):
            response = c.post(
                url,
                {
                    "decision": "approve",
                    "reason": "Approved cover by company administrator.",
                },
                HTTP_HX_REQUEST="true",
            )
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.balance.refresh_from_db()
        self.assertEqual(
            (self.item.status, self.balance.available_days), ("approved", 9)
        )
        self.assertIn(
            "Administrator intervention",
            self.item.leaverequestcomment_set.get().comment,
        )

    def test_sequential_chain_skips_self_without_skipping_other_manager(self):
        self.role()
        self.role("Leave Manager", user=self.manager.employee_user_id)
        LeaveRequestConditionApproval.objects.create(
            leave_request_id=self.item, manager_id=self.manager, sequence=2
        )
        LeaveRequestConditionApproval.objects.create(
            leave_request_id=self.item, manager_id=self.employee, sequence=1
        )
        self.assertFalse(can_approve_own_leave(self.user, self.item))
        self.assertTrue(
            self.item.leaverequestconditionapproval_set.get(sequence=1).is_approved
        )
        self.assert_pending()
        with patch("leave.views.LeaveMailSendThread.start"):
            response = self.client_as(self.manager.employee_user_id).get(
                f"/leave/request-approve/{self.item.pk}/", HTTP_HX_REQUEST="true"
            )
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.balance.refresh_from_db()
        self.assertEqual(
            (self.item.status, self.balance.available_days), ("approved", 9)
        )
        self.assertEqual(self.item.leaverequestcomment_set.count(), 1)

    def test_all_self_chain_stays_pending_for_explicit_exception(self):
        self.role("Admin")
        for sequence in (1, 2):
            LeaveRequestConditionApproval.objects.create(
                leave_request_id=self.item, manager_id=self.employee, sequence=sequence
            )
        self.client_as().get(
            f"/leave/request-approve/{self.item.pk}/", HTTP_HX_REQUEST="true"
        )
        self.assert_pending()
