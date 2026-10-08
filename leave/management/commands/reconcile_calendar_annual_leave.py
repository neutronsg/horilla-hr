"""Preview/apply the transition of existing annual balances to calendar years."""

import json
from datetime import date

from django.core.management.base import BaseCommand
from django.utils import timezone

from leave.annual_policy import _approved_current_year_days, entitlement_for_assignment, sync_annual_leave
from leave.models import AvailableLeave


class Command(BaseCommand):
    help = "Preview annual balances by default; --apply reconciles existing assignments. Does not invent historical carryforward."

    def add_arguments(self, parser):
        parser.add_argument("--as-of", type=date.fromisoformat)
        parser.add_argument("--employee", action="append", default=[])
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        as_of = options["as_of"] or timezone.localdate()
        assignments = AvailableLeave._base_manager.filter(leave_type_id__auto_leave_policy="annual").select_related("employee_id", "leave_type_id")
        if options["employee"]:
            assignments = assignments.filter(employee_id__badge_id__in=options["employee"])
        for assignment in assignments:
            result = entitlement_for_assignment(assignment, as_of)
            if not result:
                self.stdout.write(json.dumps({"employee": assignment.employee_id.badge_id, "error": "Missing joining date"}))
                continue
            calendar_basis = assignment.auto_period_basis == "calendar_year" and assignment.auto_service_year_start
            if calendar_basis and assignment.auto_service_year_start == result.service_year_start:
                new_available = assignment.available_days + result.earned_days - assignment.auto_entitlement_days
            else:
                # Joining-date corrections are rebuilt from 1 January, as in sync_annual_leave.
                usage_start = date(result.service_year_start.year, 1, 1) if calendar_basis else result.service_year_start
                new_available = result.earned_days - _approved_current_year_days(assignment, usage_start, as_of)
            row = {"assignment": assignment.pk, "employee": assignment.employee_id.badge_id,
                   "leave_type": assignment.leave_type_id.name, "old_period": assignment.auto_service_year_start,
                   "new_period": result.service_year_start, "old_available": assignment.available_days,
                   "new_available": new_available, "earned": result.earned_days,
                   "existing_carryforward": assignment.carryforward_days, "applied": options["apply"]}
            if options["apply"]:
                updated = sync_annual_leave(assignment.employee_id, assignment.leave_type_id, as_of)
                row["new_available"] = updated.available_days
                row["carryforward"] = updated.carryforward_days
            self.stdout.write(json.dumps(row, default=str))
