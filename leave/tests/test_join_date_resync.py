"""Correcting a joining date recalculates automatic annual leave."""

from datetime import date
from unittest.mock import patch

from django.test import TestCase

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
