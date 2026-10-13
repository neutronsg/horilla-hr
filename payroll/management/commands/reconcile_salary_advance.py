"""Preview or reconcile an explicitly identified duplicate manual advance."""
import copy
import json
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from payroll.advances import annotate_deduction_sources, is_manual_advance_title
from payroll.models.models import Deduction, LoanAccount, Payslip


class Command(BaseCommand):
    help = "Reconcile a matching manual advance with its Salary Advances record; previews by default."

    def add_arguments(self, parser):
        parser.add_argument("--loan-id", type=int, required=True)
        parser.add_argument("--manual-deduction-id", type=int, required=True)
        parser.add_argument("--apply", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        loan = LoanAccount._base_manager.select_for_update().get(pk=options["loan_id"])
        manual = Deduction._base_manager.select_for_update().get(pk=options["manual_deduction_id"])
        installments = list(loan.deduction_ids.all())
        money = lambda amount: Decimal(str(amount or 0)).quantize(Decimal(".01"))
        if (loan.type != "advanced_salary" or loan.settled or not loan.is_active
                or loan.installments != 1 or len(installments) != 1
                or not is_manual_advance_title(manual.title)
                or manual.update_compensation != "net_pay" or not manual.is_fixed
                or manual.is_installment or manual.is_condition_based or manual.include_active_employees
                or set(manual.specific_employees.values_list("pk", flat=True)) != {loan.employee_id_id}
                or manual.one_time_date != loan.installment_start_date
                or money(manual.amount) != money(loan.loan_amount) or manual.employer_rate):
            raise CommandError("The records are not an exact, employee-specific duplicate advance. Review them manually.")
        installment = installments[0]
        if (not installment.is_active or not installment.is_installment
                or installment.one_time_date != manual.one_time_date
                or money(installment.amount) != money(manual.amount)
                or set(installment.specific_employees.values_list("pk", flat=True)) != {loan.employee_id_id}):
            raise CommandError("The Salary Advances repayment does not match the manual deduction.")
        groups = ("basic_pay_deductions", "gross_pay_deductions", "pretax_deductions",
                  "post_tax_deductions", "tax_deductions", "net_deductions")
        changes = []
        for slip in Payslip._base_manager.select_for_update().filter(employee_id=loan.employee_id):
            data = copy.deepcopy(slip.pay_head_data)
            rows = [row for group in groups for row in data.get(group, [])]
            old = [row for row in rows if row.get("deduction_id") == manual.pk]
            if not old:
                continue
            if slip.status != "draft" or slip.sent_to_employee:
                raise CommandError(f"Payslip {slip.pk} is finalized or sent. It requires an explicit payroll correction.")
            if len(old) != 1 or money(old[0]["amount"]) != money(manual.amount):
                raise CommandError(f"Payslip {slip.pk} has a different manual advance amount.")
            canonical = [row for row in rows if row.get("deduction_id") == installment.pk]
            if len(canonical) > 1 or (canonical and money(canonical[0]["amount"]) != money(installment.amount)):
                raise CommandError(f"Payslip {slip.pk} has inconsistent repayment records.")
            if canonical and canonical[0] in data.get("pretax_deductions", []) and data.get("federal_tax"):
                raise CommandError(f"Payslip {slip.pk} requires tax recalculation before reconciling.")
            if old[0] not in data.get("net_deductions", []):
                raise CommandError(f"Payslip {slip.pk} applies the manual advance outside net pay.")
            for group in groups:
                data[group] = [row for row in data.get(group, []) if row.get("deduction_id") not in {manual.pk, installment.pk}]
            repayment = dict(canonical[0] if canonical else old[0])
            repayment.update(deduction_id=installment.pk, title=installment.title,
                             loan_account_id=loan.pk, is_pretax=False)
            data["post_tax_deductions"].append(repayment)
            removed = money(old[0]["amount"]) if canonical else Decimal("0")
            if canonical and canonical[0] in slip.pay_head_data.get("pretax_deductions", []):
                data["taxable_gross_pay"] = float(money(data.get("taxable_gross_pay")) + money(installment.amount))
            data["net_pay"] = float(money(slip.net_pay) + removed)
            data["total_deductions"] = float(money(slip.deduction) - removed)
            changes.append({"payslip": slip.pk, "removed_duplicate": float(removed),
                            "old_net": slip.net_pay, "new_net": data["net_pay"]})
            if options["apply"]:
                slip.pay_head_data = annotate_deduction_sources(data)
                slip.net_pay, slip.deduction = data["net_pay"], data["total_deductions"]
                slip._change_reason = f"Reconciled manual advance {manual.pk} with salary advance {loan.pk}; one repayment retained."
                slip.save()
                slip.installment_ids.add(installment)
        if options["apply"]:
            Deduction._base_manager.filter(pk=manual.pk).update(is_active=False)
            Deduction._base_manager.filter(pk=installment.pk).update(is_pretax=False)
        self.stdout.write(json.dumps({"loan": loan.pk, "archived_manual_deduction": manual.pk,
                                     "repayment_deduction": installment.pk, "payslips": changes,
                                     "applied": options["apply"]}))
