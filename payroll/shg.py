"""Singapore SHG deductions from dated HR declarations, independent of salary structures.

Sources: CPF Board SHG tables, CDAC/EA/SINDA employer guidance and MUIS
Employer Information. Current rates are verified for salary years 2025–2027.
No identity numbers, inferred ethnicity, or employee job-title heuristics are used.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.exceptions import ValidationError

FUNDS = ("cdac", "ecf", "sinda", "mbmf")
RATES = {
    "cdac": [(2000, ".50"), (3500, "1"), (5000, "1.50"), (7500, "2"), (None, "3")],
    "ecf": [(1000, "2"), (1500, "4"), (2500, "6"), (4000, "9"), (7000, "12"), (10000, "16"), (None, "20")],
    "sinda": [(1000, "1"), (1500, "3"), (2500, "5"), (4500, "7"), (7500, "9"), (10000, "12"), (15000, "18"), (None, "30")],
    "mbmf": [(1000, "3"), (2000, "4.50"), (3000, "6.50"), (4000, "15"), (6000, "19.50"), (8000, "22"), (10000, "24"), (None, "26")],
}


def money(value):
    return Decimal(str(value or 0)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)


def contribution(fund, wages):
    wages = money(wages)
    if wages < 0:
        raise ValidationError("Self-help group wages cannot be negative.")
    if not wages:
        return Decimal("0")
    return next(Decimal(amount) for ceiling, amount in RATES[fund] if ceiling is None or wages <= ceiling)


def validate_adjustments(adjustments):
    if not isinstance(adjustments, dict) or set(adjustments) - set(FUNDS):
        raise ValidationError("Unknown self-help group adjustment.")
    for fund, item in adjustments.items():
        if not isinstance(item, dict) or set(item) - {"mode", "amount", "reference"}:
            raise ValidationError(f"Invalid {fund.upper()} adjustment.")
        if item.get("mode") not in {"opt_out", "fixed", "voluntary"}:
            raise ValidationError("Use automatic calculation or a documented opt-out / fixed contribution.")
        if not isinstance(item.get("reference"), str) or not item["reference"].strip():
            raise ValidationError(f"Record the {fund.upper()} application / certificate reference.")
        if len(item["reference"]) > 255:
            raise ValidationError("Contribution reference is too long.")
        if item["mode"] == "opt_out":
            if item.get("amount") not in (None, "", "0", 0):
                raise ValidationError("An opt-out cannot specify a contribution amount.")
        else:
            try:
                amount = Decimal(str(item.get("amount")))
                if not amount.is_finite() or amount <= 0 or amount != money(amount) or amount > Decimal("99999.99"):
                    raise InvalidOperation
            except (InvalidOperation, ValueError, TypeError):
                raise ValidationError(f"Enter a positive {fund.upper()} contribution with at most two decimal places.")


def uses_singapore_payroll(employee):
    from employee.singapore_models import SingaporeContributionProfile, SingaporeEmployeeDetails
    company = getattr(employee.employee_work_info, "company_id", None)
    return (str(getattr(company, "country", "")).strip().casefold() in {"singapore", "sg", "sgp"}
            or SingaporeEmployeeDetails.objects.filter(employee=employee).exists()
            or SingaporeContributionProfile.objects.filter(employee=employee).exists())


def profile_for(employee, month):
    from employee.singapore_models import SingaporeContributionProfile
    return SingaporeContributionProfile.objects.filter(employee=employee,
        effective_month__lte=month.replace(day=1)).order_by("-effective_month", "-pk").first()


def applicable_funds(profile, end):
    local = profile.residency_status == "citizen" or (
        profile.residency_status == "pr" and profile.pr_effective_date <= end)
    funds = []
    if local and profile.primary_race == "chinese":
        funds.append("cdac")
    elif local and profile.primary_race == "eurasian":
        funds.append("ecf")
    elif profile.primary_race == "indian" and (local or
            (profile.residency_status == "foreigner" and profile.work_pass_type == "EP")):
        funds.append("sinda")
    if profile.muslim_status == "yes":
        funds.append("mbmf")
    return funds


def _student_exemptions(profile, contract, start, end):
    if not (profile.student_cpf_exempt or profile.student_mbmf_exempt):
        return set()
    first, last = profile.student_exempt_from, profile.student_exempt_until
    overlaps = first <= end and last >= start
    covered = first <= start and last >= end
    if overlaps and not covered:
        raise ValidationError("Student exemption changes within this pay period. Review/consolidate that transition before generating payroll.")
    if profile.student_cpf_exempt and profile.residency_status in {"citizen", "pr"}:
        if covered and not contract.cpf_exempt:
            raise ValidationError("Confirm the verified student CPF exemption on the payroll contract as well.")
        if not covered and contract.cpf_exempt:
            raise ValidationError("The contract CPF exemption extends beyond the verified student exemption dates. Review the contract.")
    exempt = set()
    if covered and profile.student_cpf_exempt:
        exempt.update({"cdac", "ecf", "sinda"})
    if covered and profile.student_mbmf_exempt:
        exempt.add("mbmf")
    return exempt


def fund_wages(fund, basic_wages, allowances):
    total = Decimal(str(basic_wages))
    for item in allowances:
        if item.get("cpf_wage_type") not in {"ow", "aw", "excluded"}:
            raise ValidationError("Classify allowance wages before calculating self-help group contributions.")
        if item["cpf_wage_type"] != "excluded" and fund not in item.get("shg_excluded_funds", []):
            total += Decimal(str(item["amount"]))
    if total < 0:
        raise ValidationError("Self-help group wages cannot be negative.")
    return money(total)


def calculate_shg(employee, contract, start, end, basic_wages, allowances, *, wages_from=None):
    if not uses_singapore_payroll(employee):
        return None
    from payroll.cpf import assert_single_cpf_month
    assert_single_cpf_month(employee, start, end)
    month = end.replace(day=1)
    if month.year not in {2025, 2026, 2027}:
        raise ValidationError("Review self-help group rate tables before calculating this salary year.")
    profile = profile_for(employee, month)
    if profile is None:
        raise ValidationError("Confirm this employee's self-help group contribution profile for the salary month in Singapore employment details.")
    profile.full_clean()
    funds = applicable_funds(profile, end)
    exempt = _student_exemptions(profile, contract, start, end)
    rows = []
    for fund in FUNDS:
        adjustment = profile.fund_adjustments.get(fund, {})
        mode = adjustment.get("mode", "auto")
        eligible = fund in funds
        if mode == "fixed" and not eligible:
            raise ValidationError(f"{fund.upper()} is not applicable to this declaration. Use a documented voluntary contribution if requested.")
        if not eligible and mode != "voluntary":
            continue
        salary, components = basic_wages, allowances
        if (fund != "mbmf" and mode != "voluntary" and profile.residency_status == "pr"
                and start < profile.pr_effective_date <= end):
            if profile.primary_race == "indian":
                # An EP holder may already owe SINDA before becoming PR. Do not guess the pass.
                from employee.singapore_models import SingaporeContributionProfile
                prior = SingaporeContributionProfile.objects.filter(employee=employee,
                    effective_month__lt=month).order_by("-effective_month", "-pk").first()
                if prior is None:
                    raise ValidationError("Confirm the Indian employee's pre-PR work-pass history for this transition month.")
                if prior.residency_status != "foreigner" or prior.primary_race != "indian":
                    raise ValidationError("Review the Indian employee's pre-PR declaration: residency and race history are inconsistent.")
                already_sinda = "sinda" in applicable_funds(prior, start)
            else:
                already_sinda = False
            if not already_sinda:
                if wages_from is None:
                    raise ValidationError("Recompute eligible wages from the PR effective date for this transition month.")
                salary, components = wages_from(profile.pr_effective_date)
        wages = fund_wages(fund, salary, components)
        standard = contribution(fund, wages) if eligible and fund not in exempt else Decimal("0")
        amount = standard
        if mode == "opt_out":
            amount = Decimal("0")
        elif mode in {"fixed", "voluntary"}:
            if fund in exempt and mode != "voluntary":
                raise ValidationError(f"{fund.upper()} student exemption applies. Use documented voluntary treatment if requested.")
            amount = money(adjustment["amount"]) if wages > 0 else Decimal("0")
        rows.append({"fund": fund, "wages": float(wages), "standard_amount": float(standard),
                     "amount": float(amount), "treatment": "student_exempt" if fund in exempt and mode == "auto" else mode})
    return {"version": "sg-shg-2025-2027-v1", "month": month.isoformat(), "profile_id": profile.pk,
            "funds": rows, "total": float(sum((money(r["amount"]) for r in rows), Decimal("0")))}
