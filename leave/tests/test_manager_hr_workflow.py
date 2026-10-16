from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import Group, Permission
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.test import Client, RequestFactory, TestCase, override_settings
from django.template.loader import render_to_string
from rest_framework.test import APIRequestFactory, force_authenticate
from base.models import CompanyGroupAssignment
from horilla.horilla_middlewares import _thread_locals, set_selected_company
from horilla.testkit import make_company, make_employee, clear_selected_company
from leave.models import (
    AvailableLeave,
    LeaveRequest,
    LeaveType,
    LeaveRequestConditionApproval,
)
from leave.workflow import can_decide_leave, hr_observers, has_manager_work
from leave.hr_notifications import HRLeaveNoticeThread


@override_settings(COMPANY_SCOPED_PERMISSIONS=True)
class ManagerHRWorkflowTests(TestCase):
    def setUp(self):
        _thread_locals.request = None
        clear_selected_company()
        self.company = make_company("Manager workflow QA")
        self.other_company = make_company("Other workflow QA")
        self.staff, self.manager, self.hr, self.unrelated = [
            make_employee(company=self.company, email=f"zeyu+flow-{n}@neutron.sg")
            for n in ["staff", "manager", "hr", "other-manager"]
        ]
        self.foreign = make_employee(
            company=self.other_company, email="zeyu+flow-foreign@neutron.sg"
        )
        for e in [self.staff, self.manager, self.hr, self.unrelated, self.foreign]:
            e.employee_user_id.is_new_employee = False
            e.employee_user_id.save()
        work = self.staff.employee_work_info
        work.reporting_manager_id = self.manager
        work.save()
        # Ensure the unrelated actor really is another manager, as in the bug.
        other_staff = make_employee(
            company=self.company, email="zeyu+flow-other-staff@neutron.sg"
        )
        other_work = other_staff.employee_work_info
        other_work.reporting_manager_id = self.unrelated
        other_work.save()
        self.grant(self.hr, "HR Manager", self.company)
        self.grant(self.foreign, "HR Manager", self.other_company)
        self.kind = LeaveType.objects.create(
            name="Workflow QA leave", total_days=20, require_approval="yes"
        )
        self.balance = AvailableLeave.objects.create(
            employee_id=self.staff, leave_type_id=self.kind, available_days=10
        )
        self.item = LeaveRequest.objects.create(
            employee_id=self.staff,
            leave_type_id=self.kind,
            start_date=date(2026, 11, 2),
            end_date=date(2026, 11, 2),
            description="Synthetic QA",
        )
        self.item.refresh_from_db()
        self.addCleanup(setattr, _thread_locals, "request", None)
        self.addCleanup(clear_selected_company)

    def grant(self, person, name, company):
        group, _ = Group.objects.get_or_create(name=name)
        group.permissions.set(
            Permission.objects.filter(
                codename__in=[
                    "view_leaverequest",
                    "change_leaverequest",
                    "add_leaverequest",
                    "change_employeeworkinformation",
                ]
            )
        )
        CompanyGroupAssignment.objects.create(
            user=person.employee_user_id, company=company, group=group
        )

    def context(self, person):
        r = RequestFactory().get("/", secure=True, HTTP_HOST="testserver")
        r.user = person.employee_user_id
        r.session = SessionStore()
        r.session["selected_company"] = str(self.company.pk)
        r.session.save()
        r._messages = FallbackStorage(r)
        _thread_locals.request = r
        set_selected_company(str(self.company.pk))
        return r

    def client_as(self, person):
        self.context(person)
        c = Client()
        c.force_login(
            person.employee_user_id, backend="base.auth_backends.CompanyScopedBackend"
        )
        s = c.session
        s["selected_company"] = str(self.company.pk)
        s.save()
        return c

    def assert_unchanged(self):
        self.item.refresh_from_db()
        self.balance.refresh_from_db()
        self.assertEqual(
            (self.item.status, self.balance.available_days), ("requested", 10)
        )

    def test_only_this_reporting_manager_can_decide(self):
        self.assertTrue(can_decide_leave(self.manager.employee_user_id, self.item))
        for person in [self.hr, self.unrelated, self.foreign, self.staff]:
            self.assertFalse(can_decide_leave(person.employee_user_id, self.item))
        self.assertFalse(has_manager_work(self.hr.employee_user_id))

    def test_hr_recipients_are_company_roles_with_view_access(self):
        self.assertEqual([p.pk for p in hr_observers(self.item)], [self.hr.pk])
        self.hr.employee_user_id.is_active = False
        self.hr.employee_user_id.save()
        self.assertEqual(hr_observers(self.item), [])

    def test_web_hr_and_unrelated_manager_cannot_approve_or_reject(self):
        for person in [self.hr, self.unrelated]:
            c = self.client_as(person)
            self.assertEqual(
                c.get(
                    f"/leave/request-approve/{self.item.pk}/", HTTP_HX_REQUEST="true"
                ).status_code,
                403,
            )
            self.assertEqual(
                c.post(
                    f"/leave/request-cancel/{self.item.pk}/",
                    {"reason": "Rejected"},
                    HTTP_HX_REQUEST="true",
                ).status_code,
                403,
            )
            self.assert_unchanged()

    def test_manager_approves_once_and_cannot_overwrite_with_rejection(self):
        c = self.client_as(self.manager)
        with patch("leave.views.LeaveMailSendThread.start"):
            first = c.get(
                f"/leave/request-approve/{self.item.pk}/", HTTP_HX_REQUEST="true"
            )
            self.assertEqual(first.status_code, 200)
            c.get(f"/leave/request-approve/{self.item.pk}/", HTTP_HX_REQUEST="true")
            self.assertEqual(
                c.post(
                    f"/leave/request-cancel/{self.item.pk}/",
                    {"reason": "Stale"},
                    HTTP_HX_REQUEST="true",
                ).status_code,
                403,
            )
        self.item.refresh_from_db()
        self.balance.refresh_from_db()
        self.assertEqual(
            (self.item.status, self.balance.available_days), ("approved", 9)
        )
        comments = self.item.leaverequestcomment_set.all()
        self.assertEqual(comments.count(), 1)
        self.assertIn("Manager decision", comments.first().comment)

    def test_api_single_and_bulk_deny_hr_observer(self):
        from horilla_api.api_views.leave.views import (
            LeaveRequestApproveAPIView,
            LeaveRequestRejectAPIView,
            LeaveRequestBulkApproveDeleteAPIview,
        )

        for view, data, args in [
            (LeaveRequestApproveAPIView, {}, [self.item.pk]),
            (LeaveRequestRejectAPIView, {}, [self.item.pk]),
            (
                LeaveRequestBulkApproveDeleteAPIview,
                {"leave_request_id": [self.item.pk]},
                [],
            ),
        ]:
            self.context(self.hr)
            http = APIRequestFactory().put("/", data, format="multipart")
            force_authenticate(http, user=self.hr.employee_user_id)
            response = view.as_view()(http, **({"pk": args[0]} if args else {}))
            self.assertIn(response.status_code, [200, 403])
            self.assert_unchanged()

    def test_hr_read_only_ui_has_no_normal_approval_button(self):
        r = self.context(self.hr)
        html = render_to_string(
            "cbv/leave_requests/confirmation.html",
            {"instance": self.item, "request": r, "current_date": date(2026, 10, 14)},
        )
        self.assertIn("For information", html)
        self.assertNotIn("request-approve", html)
        self.assertNotIn("request-cancel", html)

    def test_admin_intervention_requires_reason_and_audits_it(self):
        self.grant(self.hr, "Admin", self.company)
        c = self.client_as(self.hr)
        path = f"/leave/admin-intervention/{self.item.pk}/"
        with patch("leave.views.LeaveMailSendThread.start"):
            c.post(
                path, {"decision": "approve", "reason": "   "}, HTTP_HX_REQUEST="true"
            )
            self.assert_unchanged()
            response = c.post(
                path,
                {
                    "decision": "approve",
                    "reason": "Manager unavailable; authorized cover.",
                },
                HTTP_HX_REQUEST="true",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["HX-Redirect"], f"/leave/request-view/?id={self.item.pk}")
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, "approved")
        self.assertIn(
            "Manager unavailable", self.item.leaverequestcomment_set.first().comment
        )

    def test_hr_notice_is_fyi_and_manager_role_overlap_is_deduplicated(self):
        r = self.context(self.staff)
        with patch("leave.hr_notifications.notify.send") as bell, patch(
            "leave.hr_notifications.EmailMultiAlternatives.send", return_value=1
        ) as mail:
            HRLeaveNoticeThread(r, self.item, "submitted").send_notices()
            self.assertEqual(bell.call_count, 1)
            self.assertEqual(mail.call_count, 1)
            self.assertIn("For your information", bell.call_args.kwargs["verb"])
            self.grant(self.manager, "HR Manager", self.company)
            HRLeaveNoticeThread(r, self.item, "submitted").send_notices()
            self.assertEqual(
                bell.call_count, 2
            )  # manager receives the existing action notification only

    def test_notifications_run_only_after_commit_and_status_change(self):
        self.context(self.manager)
        with patch("leave.hr_notifications.HRLeaveNoticeThread.start") as start:
            with self.captureOnCommitCallbacks(execute=True):
                self.item.status = "approved"
                self.item.save()
                self.item.save()
            self.assertEqual(start.call_count, 1)

    def test_missing_manager_remains_pending_and_setting_one_reroutes(self):
        self.context(self.hr)
        work = self.staff.employee_work_info
        work.reporting_manager_id = None
        work.save()
        self.item.employee_id.employee_work_info.refresh_from_db()
        self.assertFalse(can_decide_leave(self.manager.employee_user_id, self.item))
        with patch("leave.hr_notifications.notify_new_manager") as reroute:
            with self.captureOnCommitCallbacks(execute=True):
                work.reporting_manager_id = self.manager
                work.save()
            reroute.assert_called_once()
        self.assert_unchanged()

    def test_hr_who_is_actual_manager_can_approve_as_manager(self):
        self.grant(self.manager, "HR Manager", self.company)
        self.assertTrue(can_decide_leave(self.manager.employee_user_id, self.item))

    def test_superuser_must_use_explicit_intervention_if_not_manager(self):
        user = self.hr.employee_user_id
        user.is_superuser = True
        user.save()
        self.assertFalse(can_decide_leave(user, self.item))
        response = self.client_as(self.hr).get(
            f"/leave/request-approve/{self.item.pk}/", HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 403)
        self.assert_unchanged()

    def test_inactive_manager_cannot_decide(self):
        self.manager.is_active = False
        self.manager.save()
        self.item.employee_id.employee_work_info.reporting_manager_id.refresh_from_db()
        self.assertFalse(can_decide_leave(self.manager.employee_user_id, self.item))

    def test_admin_cannot_intervene_in_other_company(self):
        self.grant(self.foreign, "Admin", self.other_company)
        response = self.client_as(self.foreign).post(
            f"/leave/admin-intervention/{self.item.pk}/",
            {"decision": "approve", "reason": "Wrong company"},
            HTTP_HX_REQUEST="true",
        )
        self.assertIn(response.status_code, [403, 404])
        self.assert_unchanged()

    def test_api_reject_requires_reason_and_cannot_overwrite(self):
        from horilla_api.api_views.leave.views import LeaveRequestRejectAPIView

        self.context(self.manager)
        for data, expected in [
            ({}, 400),
            ({"reason": "Dates conflict with staffing needs."}, 200),
            ({"reason": "Repeated"}, 403),
        ]:
            http = APIRequestFactory().put("/", data, format="multipart")
            force_authenticate(http, user=self.manager.employee_user_id)
            with patch("leave.threading.LeaveMailSendThread.start"):
                response = LeaveRequestRejectAPIView.as_view()(http, pk=self.item.pk)
            self.assertEqual(response.status_code, expected, response.data)
        self.item.refresh_from_db()
        self.balance.refresh_from_db()
        self.assertEqual(
            (self.item.status, self.balance.available_days), ("rejected", 10)
        )
        comment = self.item.leaverequestcomment_set.get()
        self.assertIn("Dates conflict", comment.comment)
        self.assertIsNotNone(comment.created_at)

    def test_admin_exception_can_complete_configured_chain_with_reason(self):
        self.grant(self.hr, "Admin", self.company)
        for index, actor in enumerate([self.manager, self.unrelated], 1):
            LeaveRequestConditionApproval.objects.create(
                leave_request_id=self.item, manager_id=actor, sequence=index
            )
        with patch("leave.views.LeaveMailSendThread.start"):
            response = self.client_as(self.hr).post(
                f"/leave/admin-intervention/{self.item.pk}/",
                {
                    "decision": "approve",
                    "reason": "Authorized cover for both unavailable managers.",
                },
                HTTP_HX_REQUEST="true",
            )
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.balance.refresh_from_db()
        self.assertEqual(
            (self.item.status, self.balance.available_days), ("approved", 9)
        )
        self.assertFalse(
            self.item.leaverequestconditionapproval_set.filter(
                is_approved=False
            ).exists()
        )
        self.assertIn(
            "Administrator intervention",
            self.item.leaverequestcomment_set.get().comment,
        )

    def test_sequential_chain_cannot_be_completed_out_of_order(self):
        for index, actor in enumerate([self.manager, self.unrelated], 1):
            LeaveRequestConditionApproval.objects.create(
                leave_request_id=self.item, manager_id=actor, sequence=index
            )
        self.assertFalse(can_decide_leave(self.unrelated.employee_user_id, self.item))
        with patch("leave.views.LeaveMailSendThread.start"):
            self.client_as(self.manager).get(
                f"/leave/request-approve/{self.item.pk}/", HTTP_HX_REQUEST="true"
            )
            self.assert_unchanged()
            self.client_as(self.unrelated).get(
                f"/leave/request-approve/{self.item.pk}/", HTTP_HX_REQUEST="true"
            )
        self.item.refresh_from_db()
        self.balance.refresh_from_db()
        self.assertEqual(
            (self.item.status, self.balance.available_days), ("approved", 9)
        )
        self.assertEqual(self.item.leaverequestcomment_set.count(), 2)

    def test_detail_ui_hides_hr_actions_and_exposes_explicit_admin_entry(self):
        r = self.context(self.hr)
        for admin in [False, True]:
            if admin:
                self.grant(self.hr, "Admin", self.company)
            html = render_to_string(
                "cbv/leave_requests/leave_request_detail_actions.html",
                {
                    "instance": self.item,
                    "request": r,
                    "current_date": date(2026, 10, 14),
                },
            )
            self.assertNotIn("request-approve", html)
            self.assertNotIn("request-cancel", html)
            self.assertEqual("admin-intervention" in html, admin)

    def test_submission_notice_runs_after_commit_once(self):
        self.context(self.staff)
        with patch("leave.hr_notifications.HRLeaveNoticeThread.start") as start:
            with self.captureOnCommitCallbacks(execute=True):
                LeaveRequest.objects.create(
                    employee_id=self.staff,
                    leave_type_id=self.kind,
                    start_date=date(2026, 11, 3),
                    end_date=date(2026, 11, 3),
                    description="Synthetic submission",
                )
                self.assertEqual(start.call_count, 0)
            self.assertEqual(start.call_count, 1)
