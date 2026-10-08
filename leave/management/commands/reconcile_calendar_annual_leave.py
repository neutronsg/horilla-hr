"""Preview/apply the transition of existing annual balances to calendar years."""

import json
from datetime import date

from django.core.management.base import BaseCommand
from django.utils import timezone

from leave.annual_policy import (
    calculate_annual_balance,
    entitlement_for_assignment,
    sync_annual_leave,
)
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
            row = {"assignment": assignment.pk, "employee": assignment.employee_id.badge_id,
                   "leave_type": assignment.leave_type_id.name, "old_period": assignment.auto_service_year_start,
                   "new_period": result.service_year_start, "old_available": assignment.available_days,
                   "earned": result.earned_days,
                   "existing_carryforward": assignment.carryforward_days, "applied": options["apply"]}
            if options["apply"]:
                updated = sync_annual_leave(
                    assignment.employee_id, assignment.leave_type_id, as_of
                )
            else:
                updated = calculate_annual_balance(assignment, as_of)
            row["new_available"] = updated.available_days
            row["carryforward"] = updated.carryforward_days
            self.stdout.write(json.dumps(row, default=str))
