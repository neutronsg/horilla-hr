"""Correcting a joining date recalculates automatic annual leave."""

import json
from datetime import date
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.management import call_command
from django.test import RequestFactory, TestCase

TODAY = date(2026, 10, 8)


class JoinDateResyncTests(TestCase):
    def setUp(self):
        from horilla.testkit import make_company, make_employee
        from leave.models import AvailableLeave, LeaveType

        self.employee = make_employee(
            company=make_company("Join Date Co"), email="joiner@test.horilla"
        )
        self.leave_type = LeaveType.objects.create(
            name="Annual Leave",
            total_days=14,
            auto_leave_policy="annual",
            carryforward_type="carryforward",
            carryforward_max=14,
        )
        self.set_joining_date(date(2026, 2, 1))
        with patch("leave.annual_policy.timezone.localdate", return_value=TODAY):
            AvailableLeave.objects.create(
                employee_id=self.employee, leave_type_id=self.leave_type
            )
        patcher = patch("leave.annual_policy.timezone.localdate", return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)

    def set_joining_date(self, joined):
        work = self.employee.employee_work_info
        work.date_joining = joined
        with self.captureOnCommitCallbacks(execute=True):
            work.save()

    def assignment(self):
        from leave.models import AvailableLeave

        return AvailableLeave._base_manager.get(
            employee_id=self.employee, leave_type_id=self.leave_type
        )

    def approve_september_leave(self, days):
        from leave.models import AvailableLeave, LeaveRequest

        request = LeaveRequest.objects.create(
            employee_id=self.employee,
            leave_type_id=self.leave_type,
            start_date=date(2026, 9, 7),
            end_date=date(2026, 9, 6 + days),
            status="approved",
            description="Approved leave",
        )
        LeaveRequest.objects.filter(pk=request.pk).update(approved_available_days=days)
        AvailableLeave._base_manager.filter(pk=self.assignment().pk).update(
            available_days=self.assignment().available_days - days
        )

    def test_earlier_joining_date_is_credited_on_save(self):
        self.assertEqual(self.assignment().available_days, 9)  # 8 months
        self.set_joining_date(date(2025, 12, 1))
        self.assertEqual(self.assignment().available_days, 12)  # 10 months

    def test_later_joining_date_rebuilds_without_phantom_carryforward(self):
        self.approve_september_leave(2)
        self.assertEqual(self.assignment().available_days, 7)
        self.set_joining_date(date(2026, 5, 1))
        assignment = self.assignment()
        self.assertEqual(assignment.available_days, 4)  # 5 months, less 2 used
        self.assertEqual(assignment.carryforward_days, 0)
        self.assertEqual(assignment.auto_service_year_start, date(2026, 5, 1))

    def test_joining_date_moved_from_last_year_into_this_year(self):
        self.set_joining_date(date(2025, 8, 11))
        self.approve_september_leave(2)
        self.set_joining_date(date(2026, 3, 1))
        assignment = self.assignment()
        self.assertEqual(assignment.available_days, 6)  # 7 months, less 2 used
        self.assertEqual(assignment.carryforward_days, 0)

    def test_unrelated_work_info_change_does_not_resync(self):
        work = self.employee.employee_work_info
        work.location = "Singapore"
        with patch("leave.signals.schedule_auto_leave_sync") as schedule:
            work.save()
        schedule.assert_not_called()

    def add_manual_credit(self, days):
        from leave.models import AvailableLeave

        AvailableLeave._base_manager.filter(pk=self.assignment().pk).update(
            available_days=self.assignment().available_days + days
        )

    def store_unsynced_previous_year(self):
        """Assignment last synced in December 2025, joining date since corrected."""
        from employee.models import EmployeeWorkInformation
        from leave.models import AvailableLeave

        AvailableLeave._base_manager.filter(pk=self.assignment().pk).update(
            auto_service_year_start=date(2025, 12, 15),
            auto_period_basis="calendar_year",
            auto_entitlement_days=0,
            available_days=0,
            carryforward_days=0,
        )
        EmployeeWorkInformation.objects.filter(employee_id=self.employee).update(
            date_joining=date(2026, 5, 1)
        )

    def test_correction_across_unsynced_year_end_has_no_phantom_carryforward(self):
        from leave.annual_policy import sync_annual_leave

        self.store_unsynced_previous_year()
        assignment = sync_annual_leave(self.employee, self.leave_type, TODAY)
        self.assertEqual(assignment.available_days, 6)
        self.assertEqual(assignment.carryforward_days, 0)

    def test_correction_keeps_manual_credit_and_approved_usage(self):
        self.approve_september_leave(2)
        self.add_manual_credit(3)
        self.assertEqual(self.assignment().available_days, 10)
        self.set_joining_date(date(2026, 5, 1))
        self.assertEqual(self.assignment().available_days, 7)  # 6 - 2 + 3

    def test_stale_previous_year_correction_keeps_current_year_approved_usage(self):
        from leave.annual_policy import sync_annual_leave
        from leave.models import AvailableLeave

        self.approve_september_leave(2)
        AvailableLeave._base_manager.filter(pk=self.assignment().pk).update(
            auto_service_year_start=date(2025, 1, 1), auto_entitlement_days=14,
            available_days=12, carryforward_days=0,
        )
        self.set_joining_date(date(2026, 5, 1))
        self.assertEqual(self.assignment().available_days, 4)  # 6 earned - 2 used
        self.assertEqual(self.assignment().carryforward_days, 0)
        for _ in range(2):
            sync_annual_leave(self.employee, self.leave_type, TODAY)
        self.assertEqual(self.assignment().available_days, 4)

    def test_stale_previous_year_correction_preserves_manual_credit(self):
        from leave.models import AvailableLeave

        self.approve_september_leave(2)
        AvailableLeave._base_manager.filter(pk=self.assignment().pk).update(
            auto_service_year_start=date(2025, 1, 1), auto_entitlement_days=14,
            available_days=15, carryforward_days=0,  # 14 - 2 used + 3 manual
        )
        self.set_joining_date(date(2026, 5, 1))
        assignment = self.assignment()
        # The +3 adjustment and -2 deduction remain in their booked year;
        # its remaining +1 is carried forward under the existing policy.
        self.assertEqual(assignment.available_days, 6)
        self.assertEqual(assignment.carryforward_days, 1)

    def test_rollover_keeps_future_leave_charged_to_its_booked_balance(self):
        from leave.annual_policy import sync_annual_leave
        from leave.models import AvailableLeave

        self.set_joining_date(date(2025, 1, 1))
        self.approve_september_leave(2)
        AvailableLeave._base_manager.filter(pk=self.assignment().pk).update(
            auto_service_year_start=date(2025, 1, 1), auto_entitlement_days=14,
            available_days=12, carryforward_days=0,
        )
        assignment = sync_annual_leave(self.employee, self.leave_type, TODAY)
        self.assertEqual(assignment.available_days, 11)
        self.assertEqual(assignment.carryforward_days, 12)  # 14 - 2 already booked

    def test_rollover_keeps_future_approved_carryforward_deductions(self):
        from leave.annual_policy import sync_annual_leave
        from leave.models import AvailableLeave, LeaveRequest

        self.set_joining_date(date(2025, 1, 1))
        self.approve_september_leave(2)
        LeaveRequest.objects.filter(employee_id=self.employee).update(
            approved_available_days=0, approved_carryforward_days=2,
        )
        AvailableLeave._base_manager.filter(pk=self.assignment().pk).update(
            auto_service_year_start=date(2025, 1, 1), auto_entitlement_days=14,
            available_days=14, carryforward_days=1,
        )
        assignment = sync_annual_leave(self.employee, self.leave_type, TODAY)
        self.assertEqual(assignment.available_days, 11)
        self.assertEqual(assignment.carryforward_days, 14)
        again = sync_annual_leave(self.employee, self.leave_type, TODAY)
        self.assertEqual((again.available_days, again.carryforward_days), (11, 14))

    def test_multiple_unsynced_years_deduct_future_leave_only_once(self):
        from leave.annual_policy import sync_annual_leave
        from leave.models import AvailableLeave, LeaveRequest

        self.set_joining_date(date(2025, 1, 1))
        self.approve_september_leave(2)
        LeaveRequest.objects.filter(employee_id=self.employee).update(
            start_date=date(2027, 9, 7), end_date=date(2027, 9, 8),
        )
        AvailableLeave._base_manager.filter(pk=self.assignment().pk).update(
            auto_service_year_start=date(2025, 1, 1), auto_entitlement_days=14,
            available_days=12, carryforward_days=0,
        )
        assignment = sync_annual_leave(self.employee, self.leave_type, date(2027, 10, 8))
        self.assertEqual((assignment.available_days, assignment.carryforward_days), (11, 14))

    def test_january_prebooking_keeps_approved_deduction_and_caps_unused_balance(self):
        from horilla.testkit import make_employee, make_user
        from leave.annual_policy import sync_annual_leave
        from leave.models import AvailableLeave, LeaveRequest
        from leave.views import leave_request_approve

        self.set_joining_date(date(2025, 1, 1))
        self.leave_type.carryforward_max = 2
        self.leave_type.save()
        admin = make_employee(
            company=self.employee.employee_work_info.company_id,
            email="approval-admin@test.horilla",
            user=make_user("approval-admin", is_superuser=True),
        )

        def approve(leave_request):
            http_request = RequestFactory().post(
                "/leave/request-approve", HTTP_HX_REQUEST="true"
            )
            http_request.user = admin.employee_user_id
            http_request.session = {}
            http_request._messages = FallbackStorage(http_request)
            with patch("leave.views.LeaveMailSendThread"), patch("leave.views.notify.send"):
                response = leave_request_approve(http_request, leave_request.pk)
            self.assertEqual(response.status_code, 200)
            leave_request.refresh_from_db()
            self.assertEqual(leave_request.status, "approved")

        request = LeaveRequest.objects.create(
            employee_id=self.employee, leave_type_id=self.leave_type,
            start_date=date(2026, 1, 5), end_date=date(2026, 1, 7),
            description="Approved in December",
        )
        AvailableLeave._base_manager.filter(pk=self.assignment().pk).update(
            auto_service_year_start=date(2025, 1, 1), auto_entitlement_days=14,
            available_days=10, carryforward_days=0,
        )
        approve(request)
        self.assertEqual(self.assignment().available_days, 7)
        assignment = sync_annual_leave(self.employee, self.leave_type, date(2026, 1, 2))
        self.assertEqual((assignment.available_days, assignment.carryforward_days), (0, 2))
        request.refresh_from_db()
        self.assertEqual((request.approved_available_days, request.approved_carryforward_days), (3, 0))
        # Subsequent approval consumes the two carried days without taking
        # extra current-year days or recording a negative carry deduction.
        next_request = LeaveRequest.objects.create(
            employee_id=self.employee, leave_type_id=self.leave_type,
            start_date=date(2026, 1, 12), end_date=date(2026, 1, 13),
            description="Approved after rollover",
        )
        approve(next_request)
        self.assertEqual((next_request.approved_available_days, next_request.approved_carryforward_days), (0, 2))
        self.assertEqual((self.assignment().available_days, self.assignment().carryforward_days), (0, 0))

    def test_preview_and_apply_match_when_cap_is_below_booked_carryforward(self):
        from leave.models import AvailableLeave, LeaveRequest

        self.set_joining_date(date(2025, 1, 1))
        self.leave_type.carryforward_max = 1
        self.leave_type.save()
        self.approve_september_leave(2)
        LeaveRequest.objects.filter(employee_id=self.employee).update(
            approved_available_days=0, approved_carryforward_days=2,
        )
        AvailableLeave._base_manager.filter(pk=self.assignment().pk).update(
            auto_service_year_start=date(2025, 1, 1), auto_entitlement_days=14,
            available_days=14, carryforward_days=1,
        )
        preview = self.reconcile()
        applied = self.reconcile("--apply")
        self.assertEqual((preview["new_available"], preview["carryforward"]), (11, 1))
        self.assertEqual(
            (preview["new_available"], preview["carryforward"]),
            (applied["new_available"], applied["carryforward"]),
        )

    def test_repeated_sync_after_correction_is_idempotent(self):
        from leave.annual_policy import sync_annual_leave

        self.approve_september_leave(2)
        self.set_joining_date(date(2026, 5, 1))
        first = self.assignment()
        for _ in range(2):
            sync_annual_leave(self.employee, self.leave_type, TODAY)
        again = self.assignment()
        self.assertEqual(
            (again.available_days, again.carryforward_days, again.auto_entitlement_days),
            (first.available_days, first.carryforward_days, first.auto_entitlement_days),
        )

    def test_january_rollover_still_carries_forward_unused_leave(self):
        from leave.annual_policy import sync_annual_leave

        self.assertEqual(self.assignment().available_days, 9)
        assignment = sync_annual_leave(self.employee, self.leave_type, date(2027, 1, 2))
        self.assertEqual(assignment.carryforward_days, 13)  # Feb-Dec 2026
        self.assertEqual(assignment.available_days, 0)
        self.assertEqual(assignment.expired_date, date(2028, 1, 1))
        self.assertEqual(assignment.auto_service_year_start, date(2027, 1, 1))

    def reconcile(self, *args):
        out = StringIO()
        call_command(
            "reconcile_calendar_annual_leave", "--as-of", TODAY.isoformat(), *args,
            stdout=out,
        )
        return json.loads(out.getvalue().strip().splitlines()[-1])

    def test_reconcile_preview_matches_apply_and_changes_nothing(self):
        self.store_unsynced_previous_year()
        preview = self.reconcile()
        self.assertEqual((preview["new_available"], preview["carryforward"]), (6, 0))
        unchanged = self.assignment()
        self.assertEqual(unchanged.auto_service_year_start, date(2025, 12, 15))
        self.assertEqual(unchanged.available_days, 0)
        applied = self.reconcile("--apply")
        self.assertEqual(
            (applied["new_available"], applied["carryforward"]),
            (preview["new_available"], preview["carryforward"]),
        )
        self.assertEqual(self.assignment().available_days, 6)

    def test_reconcile_preview_does_not_trigger_mail_automation(self):
        from django.db.models.signals import pre_save
        from horilla_automations import signals as automation_signals
        from horilla_automations.models import MailAutomation

        self.store_unsynced_previous_year()
        automation = MailAutomation.objects.create(
            title="Leave balance update", model="leave.models.AvailableLeave",
            trigger="on_update", mail_to="['employee_id__email']",
            mail_details="employee_id", condition="",
            condition_querystring="condition=available_days&condition=%21%3D&condition=-999",
            is_active=False,
        )
        MailAutomation.objects.filter(pk=automation.pk).update(is_active=True)
        automation_signals.start_automation()

        def cleanup():
            automation_signals.REFRESH_METHODS["clear_connection"]()
            for handler in automation_signals.INSTANCE_HANDLERS:
                pre_save.disconnect(handler, sender=handler.model_class)
            automation_signals.INSTANCE_HANDLERS.clear()

        self.addCleanup(cleanup)

        def immediate_thread(*args, target=None, **kwargs):
            return SimpleNamespace(start=lambda: target())

        with patch("horilla_automations.signals.send_mail") as send_mail, patch(
            "horilla_automations.signals.threading.Thread", side_effect=immediate_thread
        ):
            preview = self.reconcile()
            self.assertEqual(preview["new_available"], 6)
            self.assertEqual(self.assignment().available_days, 0)
            send_mail.assert_not_called()
            # The same active automation still runs for the actual apply.
            self.reconcile("--apply")
            send_mail.assert_called_once()

    def test_bulk_update_of_joining_date_resyncs_leave(self):
        from employee.views import save_employee_bulk_update
        from horilla.testkit import make_company, make_employee, make_user

        request = RequestFactory().post(
            "/employee/save-employee-bulk-update",
            {
                "update_fields": json.dumps(["employee_work_info__date_joining"]),
                "bulk_employee_ids": json.dumps(str([self.employee.pk])),
                "date_joining": "2026-05-01",
            },
        )
        # Horilla's login_required also requires an employee record.
        admin = make_employee(
            company=make_company("Bulk admin Co"),
            email="bulk-admin@test.horilla",
            user=make_user("bulk-admin", is_superuser=True),
        )
        request.user = admin.employee_user_id
        request.session = {}
        request._messages = FallbackStorage(request)
        with self.captureOnCommitCallbacks(execute=True):
            save_employee_bulk_update(request)
        self.assertEqual(self.assignment().available_days, 6)

    def test_import_resyncs_only_changed_joining_dates(self):
        from employee.methods.methods import bulk_create_work_info_import
        from employee.models import Employee

        Employee.objects.filter(pk=self.employee.pk).update(badge_id="JD001")
        row = {
            "Badge ID": "JD001",
            "Email": "joiner@test.horilla",
            "Date Joining": pd.Timestamp("2026-02-01"),
            "Contract End Date": None,
        }
        with patch("employee.methods.methods.threading.Thread"), patch(
            "leave.services.sync_auto_leave"
        ) as sync:
            with self.captureOnCommitCallbacks(execute=True):
                bulk_create_work_info_import([row])
            sync.assert_not_called()
            row["Date Joining"] = pd.Timestamp("2026-05-01")
            with self.captureOnCommitCallbacks(execute=True):
                bulk_create_work_info_import([row])
            sync.assert_called_once()
