"""Identify advance sources and prevent duplicate entry without guessing deductions."""


def is_manual_advance_title(title):
    return " ".join(str(title or "").lower().replace("_", " ").split()) in {
        "advance", "advances", "salary advance", "salary advances",
    }


def manual_advance_conflicts(employee, day, amount):
    from payroll.models.models import Deduction
    if not employee or not day or amount is None:
        return Deduction.objects.none()
    candidates = Deduction.objects.filter(
        specific_employees=employee, is_active=True, is_fixed=True,
        is_installment=False, update_compensation="net_pay", one_time_date=day,
        amount=amount,
    )
    return candidates.filter(pk__in=[d.pk for d in candidates if is_manual_advance_title(d.title)])


def annotate_deduction_sources(data):
    from payroll.models.models import LoanAccount
    groups = ("basic_pay_deductions", "gross_pay_deductions", "pretax_deductions",
              "post_tax_deductions", "tax_deductions", "net_deductions")
    ids = {row.get("deduction_id") for group in groups for row in data.get(group, []) if row.get("deduction_id")}
    sources = {}
    for loan in LoanAccount.objects.filter(deduction_ids__in=ids).prefetch_related("deduction_ids").distinct():
        for deduction in loan.deduction_ids.all():
            sources[deduction.pk] = loan.pk
    for group in groups:
        for row in data.get(group, []):
            if row.get("deduction_id") in sources:
                row["loan_account_id"] = sources[row["deduction_id"]]
    return data
