"""Approved annual leave debt is repaid by later credits, without losing usage."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from unittest import skipUnless
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import Client, RequestFactory, TestCase, TransactionTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from horilla.horilla_middlewares import _thread_locals, set_selected_company
from horilla.testkit import make_company, make_employee
from leave.annual_policy import sync_annual_leave
from leave.forms import LeaveRequestCreationForm
from leave.models import AvailableLeave, LeaveRequest, LeaveType
from leave.services import deduct_leave_balance

TODAY = date(2026, 10, 9)


class AnnualOverdraftTests(TestCase):
    def setUp(self):
        self.company = make_company("Annual debt QA")
        self.employee = make_employee(company=self.company, email="annual-debt@test.example")
        self.admin = make_employee(company=self.company, email="annual-debt-admin@test.example")
        user = self.admin.employee_user_id
        user.is_superuser = user.is_staff = True
        user.is_new_employee = False
        user.save()
        work = self.employee.employee_work_info
        work.date_joining = date(2026, 1, 1)
        work.reporting_manager_id = self.admin
        work.save()
        self.kind = LeaveType.objects.create(
            name="Annual debt leave", total_days=12, auto_leave_policy="annual",
            require_approval="yes", carryforward_type="carryforward", carryforward_max=3,
        )
        for target in ["leave.models.timezone.localdate", "leave.annual_policy.timezone.localdate"]:
            patcher = patch(target, return_value=TODAY)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.balance = AvailableLeave.objects.create(employee_id=self.employee, leave_type_id=self.kind)
        self.balance.available_days = 2
        self.balance.save()
        self.client = Client()
        self.client.force_login(user, backend="base.auth_backends.CompanyScopedBackend")
        session = self.client.session
        session["selected_company"] = str(self.company.pk)
        session.save()
        http = RequestFactory().get("/")
        http.user = user
        http.session = {"selected_company": str(self.company.pk)}
        _thread_locals.request = http
        self.addCleanup(setattr, _thread_locals, "request", None)
        self.addCleanup(set_selected_company, None)

    def application(self, **overrides):
        values = dict(
            employee_id=self.employee, leave_type_id=self.kind,
            start_date=date(2026, 10, 19), end_date=date(2026, 10, 21),
            start_date_breakdown="full_day", end_date_breakdown="full_day", description="QA annual advance",
        )
        values.update(overrides)
        return LeaveRequest(**values)

    def approve_web(self, item, expected_status=200):
        with patch("leave.views.LeaveMailSendThread.start"):
            response = self.client.get(f"/leave/request-approve/{item.pk}/", HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, expected_status)
        item.refresh_from_db()
        self.balance.refresh_from_db()

    def test_hr_and_self_service_can_submit_without_deducting(self):
        for actor in [self.admin, self.employee]:
            http = RequestFactory().get("/")
            http.user = actor.employee_user_id
            http.session = {"selected_company": str(self.company.pk)}
            _thread_locals.request = http
            form = LeaveRequestCreationForm(data={
                "employee_id": self.employee.pk, "leave_type_id": self.kind.pk,
                "start_date": "2026-10-19", "end_date": "2026-10-21",
                "start_date_breakdown": "full_day", "end_date_breakdown": "full_day",
                "description": "QA",
            })
            self.assertTrue(form.is_valid(), form.errors)
        item = form.save()
        self.balance.refresh_from_db()
        self.assertEqual(item.status, "requested")
        self.assertEqual(self.balance.available_days, 2)

    def test_api_submission_and_approval_accept_insufficient_annual_balance(self):
        from horilla_api.api_views.leave.views import EmployeeLeaveRequestGetCreateAPIView, LeaveRequestApproveAPIView
        data = {"leave_type_id": self.kind.pk, "start_date": "2026-10-19", "end_date": "2026-10-21", "description": "QA"}
        http = APIRequestFactory().post("/api/leave/user-request/", data, format="json")
        force_authenticate(http, user=self.employee.employee_user_id)
        response = EmployeeLeaveRequestGetCreateAPIView.as_view()(http)
        self.assertEqual(response.status_code, 201, response.data)
        item = LeaveRequest.objects.get(employee_id=self.employee)
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.available_days, 2)
        http = APIRequestFactory().put("/api/leave/request-approve/", {}, format="json")
        force_authenticate(http, user=self.admin.employee_user_id)
        response = LeaveRequestApproveAPIView.as_view()(http, pk=item.pk)
        self.assertEqual(response.status_code, 200, response.data)
        self.balance.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual((item.status, self.balance.available_days, self.balance.carryforward_days), ("approved", -1, 0))
        self.assertEqual((item.approved_available_days, item.approved_carryforward_days), (3, 0))

    def test_web_approval_goes_negative_and_repeat_does_not_deduct_twice(self):
        item = self.application()
        item.save()
        self.approve_web(item)
        self.assertEqual((item.status, self.balance.available_days, self.balance.total_leave_days), ("approved", -1, -1))
        self.approve_web(item)
        self.assertEqual(self.balance.available_days, -1)
        self.assertEqual(item.approved_available_days, 3)

    def test_next_month_credit_repays_debt_and_sync_is_idempotent(self):
        item = self.application()
        item.save()
        self.approve_web(item)
        for _ in range(2):
            sync_annual_leave(self.employee, self.kind, as_of=date(2026, 11, 9))
            self.balance.refresh_from_db()
            self.assertEqual((self.balance.available_days, self.balance.total_leave_days), (0, 0))
            self.assertEqual(self.balance.auto_entitlement_days, 10)

    def test_hr_credit_repays_debt_without_resetting_accrual(self):
        item = self.application()
        item.save()
        self.approve_web(item)
        self.balance.available_days += 1
        self.balance.save()
        sync_annual_leave(self.employee, self.kind, as_of=TODAY)
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.available_days, 0)

    def test_joining_date_correction_preserves_approved_debt(self):
        item = self.application()
        item.save()
        self.approve_web(item)
        work = self.employee.employee_work_info
        work.date_joining = date(2026, 2, 1)
        with self.captureOnCommitCallbacks(execute=True):
            work.save()
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.available_days, -2)
        self.assertEqual(self.balance.auto_entitlement_days, 8)

    def test_already_negative_balance_can_receive_another_approval(self):
        self.balance.available_days = -1
        self.balance.save()
        item = self.application(end_date=date(2026, 10, 19))
        item.save()
        self.approve_web(item)
        self.assertEqual((self.balance.available_days, item.approved_available_days), (-2, 1))

    def test_carryforward_is_consumed_without_becoming_negative(self):
        self.balance.available_days = 0
        self.balance.carryforward_days = 1
        self.balance.save()
        item = self.application()
        item.save()
        self.approve_web(item)
        self.assertEqual((self.balance.available_days, self.balance.carryforward_days, self.balance.total_leave_days), (-2, 0, -2))
        self.assertEqual((item.approved_available_days, item.approved_carryforward_days), (2, 1))

    def test_api_available_first_deduction_keeps_positive_refund_components(self):
        self.balance.available_days = -1
        self.balance.carryforward_days = 1
        item = self.application(requested_days=3)
        deduct_leave_balance(item, self.balance)
        self.assertEqual((self.balance.available_days, self.balance.carryforward_days), (-3, 0))
        self.assertEqual((item.approved_available_days, item.approved_carryforward_days), (2, 1))

    def test_half_day_overdraft_keeps_fraction(self):
        self.balance.available_days = 0
        self.balance.save()
        item = self.application(end_date=date(2026, 10, 19), start_date_breakdown="first_half", end_date_breakdown="first_half")
        item.save()
        self.approve_web(item)
        self.assertEqual((self.balance.available_days, self.balance.total_leave_days, item.approved_available_days), (-0.5, -0.5, 0.5))

    def test_rejection_returns_approved_debit_once(self):
        item = self.application()
        item.save()
        self.approve_web(item)
        for _ in range(2):
            with patch("leave.views.LeaveMailSendThread.start"):
                response = self.client.post(f"/leave/request-cancel/{item.pk}/", {"reason": "QA reversal"}, HTTP_HX_REQUEST="true")
            self.assertEqual(response.status_code, 200)
        self.balance.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual((self.balance.available_days, item.status), (2, "rejected"))
        self.assertEqual((item.approved_available_days, item.approved_carryforward_days), (0, 0))

    def test_bulk_api_approval_supports_overdraft(self):
        from horilla_api.api_views.leave.views import LeaveRequestBulkApproveDeleteAPIview
        item = self.application()
        item.save()
        http = APIRequestFactory().put("/api/leave/request-bulk-action/", {"leave_request_id": [str(item.pk)]}, format="multipart")
        force_authenticate(http, user=self.admin.employee_user_id)
        response = LeaveRequestBulkApproveDeleteAPIview.as_view()(http)
        self.assertEqual(response.status_code, 200)
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.available_days, -1)

    def test_withdrawing_hr_credit_restores_debt_on_web_and_api(self):
        from horilla_api.api_views.leave.views import LeaveAllocationRequestRejectAPIView
        from leave.models import LeaveAllocationRequest
        for via_api in [False, True]:
            self.balance.available_days = 0  # -1 debt repaid by this 1-day credit.
            self.balance.save()
            credit = LeaveAllocationRequest.objects.create(
                employee_id=self.employee, leave_type_id=self.kind,
                requested_days=1, status="approved", description="QA credit",
            )
            if via_api:
                http = APIRequestFactory().put("/api/leave/allocation-reject/", {}, format="json")
                force_authenticate(http, user=self.admin.employee_user_id)
                response = LeaveAllocationRequestRejectAPIView.as_view()(http, pk=credit.pk)
                self.assertEqual(response.status_code, 200)
            else:
                response = self.client.post(f"/leave/leave-allocation-request-reject/{credit.pk}/", {"reason": "QA credit correction"}, HTTP_HX_REQUEST="true")
                self.assertIn(response.status_code, [200, 204, 302])
            self.balance.refresh_from_db()
            credit.refresh_from_db()
            self.assertEqual((self.balance.available_days, self.balance.total_leave_days, credit.status), (-1, -1, "rejected"))

    def test_multi_stage_approval_only_deducts_at_final_stage(self):
        from django.contrib.auth.models import Group, Permission
        from base.models import CompanyGroupAssignment
        from leave.models import LeaveRequestConditionApproval
        second = make_employee(company=self.company, email="annual-final-approver@test.example")
        group = Group.objects.create(name="Annual approval QA")
        group.permissions.add(Permission.objects.get(content_type__app_label="leave", codename="change_leaverequest"))
        for actor in [self.admin, second]:
            user = actor.employee_user_id
            user.is_superuser = False
            user.is_new_employee = False
            user.save()
            CompanyGroupAssignment.objects.create(user=user, company=self.company, group=group)
        item = self.application()
        item.save()
        for sequence, actor in enumerate([self.admin, second], start=1):
            LeaveRequestConditionApproval.objects.create(leave_request_id=item, manager_id=actor, sequence=sequence)
        self.approve_web(item)
        self.assertEqual((item.status, self.balance.available_days), ("requested", 2))
        self.client.force_login(second.employee_user_id, backend="base.auth_backends.CompanyScopedBackend")
        self.approve_web(item)
        self.assertEqual((item.status, self.balance.available_days), ("approved", -1))

    def test_other_leave_types_and_auto_approval_do_not_allow_overdraft(self):
        from horilla_api.api_serializers.leave.serializers import LeaveRequestApproveSerializer
        for policy, approval in [("none", "yes"), ("outpatient_sick", "yes"), ("hospitalisation", "yes"), ("annual", "no")]:
            self.kind.auto_leave_policy, self.kind.require_approval = policy, approval
            self.kind.save()
            item = self.application()
            item.save()
            serializer = LeaveRequestApproveSerializer(item, data={})
            self.assertFalse(serializer.is_valid())
            item.delete()
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.available_days, 2)

    def test_self_approval_still_refused(self):
        item = self.application()
        item.save()
        self.client.force_login(self.employee.employee_user_id, backend="base.auth_backends.CompanyScopedBackend")
        self.approve_web(item, expected_status=204)
        self.assertEqual((item.status, self.balance.available_days), ("requested", 2))

    def test_approval_failure_rolls_back_overdraft(self):
        from django.db import DataError
        item = self.application()
        item.save()
        with patch("django.db.models.query.QuerySet.update_or_create", side_effect=DataError("QA work record failure")):
            self.approve_web(item, expected_status=404)
        item.refresh_from_db()
        self.balance.refresh_from_db()
        self.assertEqual((item.status, self.balance.available_days), ("requested", 2))

    def test_service_gate_and_before_joining_checks_remain(self):
        work = self.employee.employee_work_info
        work.date_joining = date(2026, 9, 1)
        work.save()
        http = RequestFactory().get("/")
        http.user = self.employee.employee_user_id
        _thread_locals.request = http
        with self.assertRaisesMessage(ValidationError, "three months"):
            self.application().clean()
        with self.assertRaisesMessage(ValidationError, "joining date"):
            self.application(start_date=date(2026, 8, 1), end_date=date(2026, 8, 1)).clean()

    def test_new_year_carryforward_cap_does_not_erase_debt(self):
        for carry_policy in ["no carryforward", "carryforward"]:
            self.kind.carryforward_type = carry_policy
            self.kind.carryforward_max = 0
            self.kind.save()
            sync_annual_leave(self.employee, self.kind, as_of=date(2026, 12, 31))
            self.balance.refresh_from_db()
            self.balance.available_days = -1
            self.balance.save()
            sync_annual_leave(self.employee, self.kind, as_of=date(2027, 1, 1))
            self.balance.refresh_from_db()
            self.assertEqual((self.balance.available_days, self.balance.carryforward_days, self.balance.total_leave_days), (-1, 0, -1))
            sync_annual_leave(self.employee, self.kind, as_of=date(2027, 2, 1))
            self.balance.refresh_from_db()
            self.assertEqual(self.balance.available_days, 0)


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locks")
class AnnualOverdraftConcurrencyTests(TransactionTestCase):
    def setUp(self):
        from leave.tests.test_concurrent_approval import ConcurrentApprovalTests
        ConcurrentApprovalTests.setUp(self)
        self.kind.auto_leave_policy = "annual"
        self.kind.save()

    def approve(self, index, barrier):
        from leave.tests.test_concurrent_approval import ConcurrentApprovalTests
        return ConcurrentApprovalTests.approve(self, index, barrier)

    def test_two_approvals_both_deduct_without_losing_the_overdraft(self):
        barrier = threading.Barrier(2)
        with patch("leave.views.LeaveMailSendThread.start"), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.approve, i, barrier) for i in range(2)]
            self.assertEqual([f.result(timeout=20) for f in futures], [200, 200])
        self.balance.refresh_from_db()
        for item in self.requests:
            item.refresh_from_db()
        self.assertEqual([r.status for r in self.requests], ["approved", "approved"])
        self.assertEqual(sum(r.approved_available_days for r in self.requests), 2)
        self.assertEqual((self.balance.available_days, self.balance.total_leave_days), (-1, -1))
