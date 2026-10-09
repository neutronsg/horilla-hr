"""Company HR/Admin self approval across every approval entry point."""

from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import Group, Permission
from django.test import Client, RequestFactory, TestCase, override_settings
from django.contrib.messages.storage.fallback import FallbackStorage
from rest_framework.test import APIRequestFactory, force_authenticate

from base.models import CompanyGroupAssignment
from horilla.horilla_middlewares import _thread_locals, set_selected_company
from horilla.testkit import make_company, make_employee
from leave.models import AvailableLeave, LeaveRequest, LeaveRequestConditionApproval, LeaveType
from leave.services import can_approve_own_leave


@override_settings(COMPANY_SCOPED_PERMISSIONS=True)
class SelfApprovalTests(TestCase):
    def setUp(self):
        self.company = make_company("Self approval company")
        self.other = make_company("Other self approval company")
        self.employee = make_employee(company=self.company, email="self-approve@test.horilla")
        self.manager = make_employee(company=self.company, email="second-approve@test.horilla")
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
            employee_id=self.employee, leave_type_id=self.kind,
            start_date=date(2026, 10, 19), end_date=date(2026, 10, 19), description="QA self approval",
        )
        self.addCleanup(setattr, _thread_locals, "request", None)
        self.addCleanup(set_selected_company, None)

    def role(self, name="HR Manager", company=None, permissions=("change_leaverequest", "view_leaverequest"), user=None):
        group, _ = Group.objects.get_or_create(name=name)
        group.permissions.set(Permission.objects.filter(codename__in=permissions))
        CompanyGroupAssignment.objects.create(user=user or self.user, company=company or self.company, group=group)

    def client_as(self, user=None):
        client = Client()
        client.force_login(user or self.user, backend="base.auth_backends.CompanyScopedBackend")
        session = client.session
        session["selected_company"] = str(self.company.pk)
        session.save()
        return client

    def api_request(self, bulk=False, user=None):
        http = APIRequestFactory().put("/api/leave/approve/", {"leave_request_id": [self.item.pk]} if bulk else {}, format="multipart")
        actor = user or self.user
        force_authenticate(http, user=actor)
        context = RequestFactory().get("/")
        context.user = actor
        context.session = {"selected_company": str(self.company.pk)}
        _thread_locals.request = context
        set_selected_company(str(self.company.pk))
        return http

    def assert_approved_once(self):
        self.item.refresh_from_db()
        self.balance.refresh_from_db()
        self.assertEqual((self.item.status, self.balance.available_days), ("approved", 9))
        comments = self.item.leaverequestcomment_set.all()
        self.assertEqual(comments.count(), 1)
        self.assertIn("Self-approved", comments[0].comment)
        self.assertIn("balance=9", comments[0].comment)
        self.assertIsNotNone(comments[0].created_at)

    def test_hr_and_admin_can_self_approve_with_existing_permission(self):
        for role in ("HR Manager", "Admin"):
            with self.subTest(role=role):
                CompanyGroupAssignment.objects.filter(user=self.user).delete()
                self.role(role)
                self.assertTrue(can_approve_own_leave(self.user, self.item))

    def test_role_needs_approval_permission_in_own_company(self):
        self.role(permissions=("view_leaverequest",))
        self.role("Admin", company=self.other)
        self.assertFalse(can_approve_own_leave(self.user, self.item))

    def test_manager_and_combined_non_hr_roles_do_not_gain_self_approval(self):
        self.role("Leave Manager")
        self.role("Payroll Manager", permissions=("change_employeeworkinformation",))
        self.role("Recruiter", permissions=("add_leaverequest",))
        self.assertFalse(can_approve_own_leave(self.user, self.item))
        response = self.client_as().get(f"/leave/request-approve/{self.item.pk}/", HTTP_HX_REQUEST="true")
        self.assertLess(response.status_code, 500)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, "requested")

    def test_web_self_approval_records_audit_and_repeat_does_not_charge(self):
        self.role()
        client = self.client_as()
        with patch("leave.views.LeaveMailSendThread.start"):
            for _ in range(2):
                response = client.get(f"/leave/request-approve/{self.item.pk}/", HTTP_HX_REQUEST="true")
                self.assertEqual(response.status_code, 200)
        self.assert_approved_once()

    def test_api_admin_self_approval(self):
        from horilla_api.api_views.leave.views import LeaveRequestApproveAPIView
        self.role("Admin")
        response = LeaveRequestApproveAPIView.as_view()(self.api_request(), pk=self.item.pk)
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_approved_once()

    def test_api_bulk_hr_self_approval(self):
        from horilla_api.api_views.leave.views import LeaveRequestBulkApproveDeleteAPIview
        self.role()
        response = LeaveRequestBulkApproveDeleteAPIview.as_view()(self.api_request(bulk=True))
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_approved_once()

    def test_web_bulk_admin_self_approval(self):
        self.role("Admin")
        with patch("leave.views.LeaveMailSendThread.start"):
            response = self.client_as().post("/leave/leave-requests-bulk-approve/", {"ids": [self.item.pk]}, HTTP_HX_REQUEST="true")
        self.assertLess(response.status_code, 400)
        self.assert_approved_once()

    def test_cbv_bulk_hr_self_approval(self):
        from leave.cbv.leave_requests import LeaveRequestsListView
        self.role()
        http = RequestFactory().post("/leave/request-filter/", {"instance_ids": [self.item.pk], "status": "approved"}, HTTP_HX_REQUEST="true")
        http.user = self.user
        http.session = {"selected_company": str(self.company.pk)}
        http._messages = FallbackStorage(http)
        _thread_locals.request = http
        set_selected_company(str(self.company.pk))
        with patch("leave.views.LeaveMailSendThread.start"):
            LeaveRequestsListView.handle_bulk_submission(None, http)
        self.assert_approved_once()

    def steps(self, self_first=True):
        employees = [self.employee, self.manager] if self_first else [self.manager, self.employee]
        for sequence, employee in enumerate(employees, 1):
            LeaveRequestConditionApproval.objects.create(leave_request_id=self.item, manager_id=employee, sequence=sequence)

    def test_web_self_step_keeps_other_required_approval(self):
        self.role()
        self.steps()
        with patch("leave.views.LeaveMailSendThread.start"):
            self.client_as().get(f"/leave/request-approve/{self.item.pk}/", HTTP_HX_REQUEST="true")
        self.item.refresh_from_db()
        self.balance.refresh_from_db()
        self.assertEqual((self.item.status, self.balance.available_days), ("requested", 10))
        self.assertTrue(self.item.leaverequestconditionapproval_set.get(sequence=1).is_approved)
        self.role("Leave Manager", user=self.manager.employee_user_id)
        with patch("leave.views.LeaveMailSendThread.start"):
            self.client_as(self.manager.employee_user_id).get(f"/leave/request-approve/{self.item.pk}/", HTTP_HX_REQUEST="true")
        self.item.refresh_from_db()
        self.balance.refresh_from_db()
        self.assertEqual((self.item.status, self.balance.available_days), ("approved", 9))
        self.assertEqual(self.item.leaverequestcomment_set.count(), 1)
        self.assertIn("deducted=0", self.item.leaverequestcomment_set.first().comment)

    def test_api_bulk_does_not_skip_required_steps(self):
        from horilla_api.api_views.leave.views import LeaveRequestBulkApproveDeleteAPIview
        self.role()
        self.steps()
        response = LeaveRequestBulkApproveDeleteAPIview.as_view()(self.api_request(bulk=True))
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.balance.refresh_from_db()
        self.assertEqual((self.item.status, self.balance.available_days), ("requested", 10))
        self.assertEqual(self.item.leaverequestcomment_set.count(), 1)

    def test_web_repeated_approver_can_complete_each_required_step(self):
        self.role()
        for sequence in (1, 2):
            LeaveRequestConditionApproval.objects.create(
                leave_request_id=self.item, manager_id=self.employee, sequence=sequence
            )
        client = self.client_as()
        with patch("leave.views.LeaveMailSendThread.start"):
            client.get(f"/leave/request-approve/{self.item.pk}/", HTTP_HX_REQUEST="true")
            self.balance.refresh_from_db()
            self.assertEqual(self.balance.available_days, 10)
            client.get(f"/leave/request-approve/{self.item.pk}/", HTTP_HX_REQUEST="true")
        self.balance.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual((self.item.status, self.balance.available_days), ("approved", 9))
        self.assertEqual(self.item.leaverequestcomment_set.count(), 2)

    def test_web_approval_order_uses_sequence_not_insertion_order(self):
        self.role()
        self.role("Leave Manager", user=self.manager.employee_user_id)
        LeaveRequestConditionApproval.objects.create(leave_request_id=self.item, manager_id=self.manager, sequence=2)
        LeaveRequestConditionApproval.objects.create(leave_request_id=self.item, manager_id=self.employee, sequence=1)
        with patch("leave.views.LeaveMailSendThread.start"):
            self.client_as().get(f"/leave/request-approve/{self.item.pk}/", HTTP_HX_REQUEST="true")
            self.balance.refresh_from_db()
            self.assertEqual(self.balance.available_days, 10)
            self.client_as(self.manager.employee_user_id).get(f"/leave/request-approve/{self.item.pk}/", HTTP_HX_REQUEST="true")
        self.item.refresh_from_db()
        self.balance.refresh_from_db()
        self.assertEqual((self.item.status, self.balance.available_days), ("approved", 9))

    def test_self_approval_cannot_jump_ahead_of_other_approver(self):
        from horilla_api.api_views.leave.views import LeaveRequestApproveAPIView
        self.role()
        self.steps(self_first=False)
        response = LeaveRequestApproveAPIView.as_view()(self.api_request(), pk=self.item.pk)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.item.leaverequestconditionapproval_set.filter(is_approved=True).exists())

    def test_cancelled_and_rejected_requests_cannot_be_approved_again(self):
        self.role()
        for status in ("cancelled", "rejected"):
            LeaveRequest._base_manager.filter(pk=self.item.pk).update(status=status)
            self.client_as().get(f"/leave/request-approve/{self.item.pk}/", HTTP_HX_REQUEST="true")
            self.balance.refresh_from_db()
            self.assertEqual(self.balance.available_days, 10)
        self.assertEqual(self.item.leaverequestcomment_set.count(), 0)
