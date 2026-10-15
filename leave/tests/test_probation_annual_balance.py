"""Early probation confirmation opens the annual leave balance, not only booking.

MOM: annual leave is earned after three months of service, pro-rated by
completed months ((months / 12) x entitlement, fractions of half a day or more
round up) with approved unpaid leave excluded. Neutron grants it earlier once HR
confirms probation (or none is required). That is more favourable than the
statutory minimum: the gate opens earlier, accrual is unchanged, and by the
three-month mark the balance equals the statutory amount.
"""

from datetime import date
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from horilla.horilla_middlewares import _thread_locals
from horilla.testkit import clear_selected_company, make_company, make_employee
from leave.annual_entitlement import calculate_entitlement
from leave.annual_policy import sync_annual_leave
from leave.models import AvailableLeave, LeaveRequest, LeaveType

JOINED = date(2026, 7, 20)
CONFIRMED = date(2026, 10, 6)
TODAY = date(2026, 10, 15)  # two completed months of service
THREE_MONTHS = date(2026, 10, 20)


def earned(as_of, opens_on=None, joined=JOINED, days=14, basis="calendar_year"):
    return calculate_entitlement(
        joined, as_of, configured_annual_days=days, period_basis=basis, opens_on=opens_on
    ).earned_days


class EntitlementGateTests(SimpleTestCase):
    def test_statutory_gate_without_confirmation(self):
        self.assertEqual(earned(TODAY), 0)
        self.assertEqual(earned(THREE_MONTHS), 4)  # 3 x 14/12 = 3.5, half rounds up

    def test_early_confirmation_opens_pro_rata_balance(self):
        self.assertEqual(earned(date(2026, 10, 5), opens_on=CONFIRMED), 0)  # before confirmation
        self.assertEqual(earned(CONFIRMED, opens_on=CONFIRMED), 2)  # 2 x 14/12 = 2.33
        self.assertEqual(earned(TODAY, opens_on=CONFIRMED), 2)

    def test_three_month_balance_is_the_same_either_way(self):
        for as_of in (THREE_MONTHS, date(2026, 12, 31), date(2027, 3, 31)):
            self.assertEqual(earned(as_of, opens_on=CONFIRMED), earned(as_of), as_of)

    def test_a_later_date_never_delays_the_statutory_gate(self):
        self.assertEqual(earned(THREE_MONTHS, opens_on=date(2026, 12, 1)), earned(THREE_MONTHS))

    def test_service_year_basis_uses_the_same_gate(self):
        self.assertEqual(earned(TODAY, basis="service_year"), 0)
        self.assertEqual(earned(TODAY, opens_on=CONFIRMED, basis="service_year"), 2)
        self.assertEqual(
            earned(THREE_MONTHS, opens_on=CONFIRMED, basis="service_year"),
            earned(THREE_MONTHS, basis="service_year"),
        )

    def test_mom_worked_example(self):
        # MOM: 4 completed months with 10 days' entitlement = 3.33, rounded down to 3.
        joined = date(2026, 1, 1)
        self.assertEqual(earned(date(2026, 4, 30), joined=joined, days=10, basis="service_year"), 3)


class ProbationBalanceTests(TestCase):
    def setUp(self):
        _thread_locals.request = None
        clear_selected_company()
        for target in ("leave.annual_policy.timezone.localdate", "employee.probation.timezone.localdate"):
            patcher = patch(target, return_value=TODAY)
            patcher.start()
            self.addCleanup(patcher.stop)
        company = make_company("Probation balance QA")
        self.kind = LeaveType.objects.create(
            name="Annual leave", total_days=14, auto_leave_policy="annual",
            require_approval="yes", carryforward_type="carryforward", carryforward_max=14,
        )
        self.confirmed = self.hire(company, "confirmed")
        self.control = self.hire(company, "control")

    def hire(self, company, name):
        employee = make_employee(company=company, email=f"zeyu+al-{name}@neutron.sg")
        work = employee.employee_work_info
        work.date_joining = JOINED
        work.save()
        AvailableLeave.objects.create(employee_id=employee, leave_type_id=self.kind)
        return employee

    def balance(self, employee):
        return AvailableLeave._base_manager.get(employee_id=employee, leave_type_id=self.kind)

    def set_probation(self, employee, status, passed_on=None):
        work = type(employee.employee_work_info)._base_manager.get(employee_id=employee)
        work.probation_status = status
        work.probation_passed_on = passed_on
        with self.captureOnCommitCallbacks(execute=True):
            work.save()

    def test_confirming_probation_credits_earned_days_on_save(self):
        self.assertEqual(self.balance(self.confirmed).available_days, 0)
        self.set_probation(self.confirmed, "passed", CONFIRMED)
        self.assertEqual(self.balance(self.confirmed).available_days, 2)
        self.assertEqual(self.balance(self.control).available_days, 0)

    def test_no_double_credit_when_three_months_are_completed(self):
        self.set_probation(self.confirmed, "passed", CONFIRMED)
        for employee in (self.confirmed, self.control):
            sync_annual_leave(employee, self.kind, THREE_MONTHS)
            sync_annual_leave(employee, self.kind, THREE_MONTHS)  # idempotent
        self.assertEqual(self.balance(self.confirmed).available_days, 4)
        self.assertEqual(self.balance(self.control).available_days, 4)

    def test_no_probation_required_accrues_from_joining(self):
        self.set_probation(self.confirmed, "not_required")
        self.assertEqual(self.balance(self.confirmed).available_days, 2)

    def test_expected_end_alone_does_not_open_leave(self):
        work = self.confirmed.employee_work_info
        work.probation_status = "on_probation"
        work.probation_end = CONFIRMED
        with self.captureOnCommitCallbacks(execute=True):
            work.save()
        self.assertEqual(self.balance(self.confirmed).available_days, 0)

    def test_reverting_confirmation_keeps_used_days_charged(self):
        self.set_probation(self.confirmed, "passed", CONFIRMED)
        request = LeaveRequest.objects.create(
            employee_id=self.confirmed, leave_type_id=self.kind,
            start_date=date(2026, 10, 12), end_date=date(2026, 10, 13),
            status="approved", description="Synthetic QA",
        )
        LeaveRequest.objects.filter(pk=request.pk).update(approved_available_days=2)
        AvailableLeave._base_manager.filter(pk=self.balance(self.confirmed).pk).update(available_days=0)
        self.set_probation(self.confirmed, "on_probation")
        self.assertEqual(self.balance(self.confirmed).available_days, -2)  # deficit retained
        sync_annual_leave(self.confirmed, self.kind, THREE_MONTHS)
        self.assertEqual(self.balance(self.confirmed).available_days, 2)  # 4 earned, 2 used

    def test_year_end_rollover_matches_the_statutory_path(self):
        joined, confirmed = date(2026, 11, 2), date(2026, 12, 10)
        for employee in (self.confirmed, self.control):
            work = type(employee.employee_work_info)._base_manager.get(employee_id=employee)
            work.date_joining = joined
            with self.captureOnCommitCallbacks(execute=True):
                work.save()
        with patch("employee.probation.timezone.localdate", return_value=date(2026, 12, 15)):
            self.set_probation(self.confirmed, "passed", confirmed)
        sync_annual_leave(self.confirmed, self.kind, date(2026, 12, 15))
        self.assertEqual(self.balance(self.confirmed).available_days, 1)  # 1 x 14/12, early
        for employee in (self.confirmed, self.control):
            sync_annual_leave(employee, self.kind, date(2027, 2, 10))
        early, statutory = self.balance(self.confirmed), self.balance(self.control)
        self.assertEqual(
            (early.available_days + early.carryforward_days),
            (statutory.available_days + statutory.carryforward_days),
        )
