"""Recalculate one draft without publishing or notifying an employee."""

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from payroll.methods.methods import calculate_employer_contribution
from payroll.models.models import Payslip
from payroll.views.component_views import payroll_calculation


class Command(BaseCommand):
    help = "Preview a draft's calculated pay; --apply updates that draft only."

    def add_arguments(self, parser):
        parser.add_argument("--id", type=int, required=True)
        parser.add_argument("--apply", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        slip = Payslip._base_manager.select_for_update().get(pk=options["id"])
        if slip.status != "draft":
            raise CommandError("Only draft payslips can be recalculated.")
        calculated = payroll_calculation(slip.employee_id, slip.start_date, slip.end_date)
        payload = json.loads(calculated["json_data"])
        calculate_employer_contribution({"pay_data": payload})
        row = {"payslip": slip.pk, "employee": slip.employee_id.badge_id,
               "old_gross": slip.gross_pay, "old_net": slip.net_pay,
               "new_gross": round(calculated["gross_pay"], 2), "new_net": round(calculated["net_pay"], 2),
               "new_deductions": round(calculated["total_deductions"], 2),
               "proration": calculated["proration"], "sdl_exempt": payload["sdl_exempt"], "applied": options["apply"]}
        if options["apply"]:
            for field, key in (("basic_pay", "basic_pay"), ("gross_pay", "gross_pay"), ("net_pay", "net_pay"), ("contract_wage", "contract_wage"), ("deduction", "total_deductions")):
                setattr(slip, field, round(calculated[key], 2))
            slip.start_date, slip.end_date = calculated["start_date"], calculated["end_date"]
            slip.pay_head_data = payload
            slip.save()
            slip.installment_ids.set(calculated["installments"])
        self.stdout.write(json.dumps(row, default=str))
