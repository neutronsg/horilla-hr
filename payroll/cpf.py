"""Singapore private-sector CPF, using CPF Board's 2025–2027 tables.

Sources and operational limits are recorded in docs/hr-payroll-quick-setup.md.
No identity-number fields are fetched. All arithmetic before rendering is Decimal.
"""
from datetime import date, timedelta
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db.models import Q

def D(value):
    return Decimal(str(value or 0))

# (employee %, employer %), ordered by <=55, <=60, <=65, <=70, >70.
FULL_RATES = {
    2025: [(20, 17), (17, 15.5), (11.5, 12), (7.5, 9), (5, 7.5)],
    2026: [(20, 17), (18, 16), (12.5, 12.5), (7.5, 9), (5, 7.5)],
    2027: [(20, 17), (19, 16.5), (13, 13), (7.5, 9), (5, 7.5)],
}
PR_RATES = {
    1: [(5, 4), (5, 4), (5, 3.5), (5, 3.5), (5, 3.5)],
    2: [(15, 9), (12.5, 6), (7.5, 3.5), (5, 3.5), (5, 3.5)],
}


def age_band(dob, month):
    if not dob or dob > month:
        raise ValidationError("Record a valid date of birth before calculating statutory CPF.")
    # Lower rates start in the month AFTER the birthday, including a birthday on day 1.
    prior = month - timedelta(days=1)
    age = prior.year - dob.year - ((prior.month, prior.day) < (dob.month, dob.day))
    return next((i for i, upper in enumerate((55, 60, 65, 70)) if age < upper), 4)


def contribution_rates(month, dob, residency, pr_date=None, scheme="graduated", approval="", scheme_start=None):
    if month.year not in FULL_RATES:
        raise ValidationError("Statutory CPF tables are verified for 2025–2027 only.")
    if scheme != "graduated":
        if not approval.strip():
            raise ValidationError("Record CPF Board approval before using higher PR rates.")
        if scheme_start is None or scheme_start.day != 1:
            raise ValidationError("Record the approved higher-rate effective month using its first day.")
        if month < scheme_start:
            scheme = "graduated"
    band = age_band(dob, month)
    rates = FULL_RATES[month.year][band]
    pr_year = 3
    if residency == "pr":
        if pr_date is None:
            raise ValidationError("Record the PR effective date before calculating CPF.")
        # Compare month starts, so the anniversary month retains its prior year rate.
        pr_year = min(3, 1 + max(0, month.year - pr_date.year - (month.month <= pr_date.month)))
        if pr_year < 3:
            graduated = PR_RATES[pr_year][band]
            if scheme != "graduated" and not approval.strip():
                raise ValidationError("Record CPF Board approval before using higher PR rates.")
            if scheme == "graduated":
                rates = graduated
            elif scheme == "full_employer":
                rates = (graduated[0], rates[1])
            elif scheme != "full_both":
                raise ValidationError("Unknown PR CPF scheme.")
    return D(rates[0]) / 100, D(rates[1]) / 100, pr_year


def contribution_amounts(ow, aw, employee_rate, employer_rate, total_wages=None):
    wages = D(ow) + D(aw)
    threshold_wages = wages if total_wages is None else D(total_wages)
    if threshold_wages <= 50:
        return 0, 0
    if threshold_wages <= 500:
        employee_raw = D(0)
    elif threshold_wages <= 750:
        employee_raw = employee_rate * 3 * (threshold_wages - 500)
    else:
        employee_raw = employee_rate * wages
    total = (employer_rate * wages + employee_raw).quantize(D(1), rounding=ROUND_HALF_UP)
    employee = employee_raw.quantize(D(1), rounding=ROUND_DOWN)
    return int(employee), int(total - employee)


def cpf_details(employee, contract):
    from employee.singapore_models import SingaporeEmployeeDetails
    from payroll.models.models import Deduction
    details = SingaporeEmployeeDetails.objects.filter(employee=employee).only(
        "residency_status", "pr_effective_date"
    ).first()
    targets = Q(specific_employees=employee) | Q(include_active_employees=True)
    if contract.salary_structure_id:
        targets |= Q(salary_structures=contract.salary_structure_id)
    configured = Deduction.objects.filter(statutory_type="cpf").filter(targets).exists()
    if contract.cpf_exempt:
        if not contract.cpf_exemption_reason.strip():
            raise ValidationError("Record the CPF exemption basis.")
        return None
    if details is None or not details.residency_status:
        company = getattr(employee.employee_work_info, "company_id", None)
        singapore_company = str(getattr(company, "country", "")).strip().casefold() in {"singapore", "sg", "sgp"}
        if configured or singapore_company:
            raise ValidationError("Record Singapore residency status before calculating CPF.")
        return None
    if details.residency_status not in {"citizen", "pr", "foreigner"}:
        raise ValidationError("Unknown Singapore residency status.")
    return details


def assert_single_cpf_month(employee, start, end, exclude_pk=None):
    from payroll.models.models import Payslip
    month = end.replace(day=1)
    if start.replace(day=1) != month:
        raise ValidationError("Generate statutory CPF payroll separately for each calendar month.")
    # Monthly consolidation is required for the wage ceiling, low-wage rules and rounding.
    other = Payslip._base_manager.filter(employee_id=employee,
        end_date__gte=month)
    next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    other = other.filter(start_date__lt=next_month)
    if exclude_pk is not None:
        other = other.exclude(pk=exclude_pk)
    else:
        other = other.exclude(start_date=start, end_date=end)
    if other.exists():
        raise ValidationError("Consolidate this employee's wages into one CPF payslip per calendar month.")


def calculate_cpf(employee, contract, start, end, basic_wages, allowances, details):
    if details is None or details.residency_status == "foreigner":
        return None
    assert_single_cpf_month(employee, start, end)
    month = end.replace(day=1)
    if details.residency_status == "pr":
        if details.pr_effective_date is None:
            raise ValidationError("Record the PR effective date before calculating CPF.")
        if details.pr_effective_date > end:
            return None
    erate, rrate, pr_year = contribution_rates(month, employee.dob,
        details.residency_status, details.pr_effective_date,
        contract.cpf_pr_scheme, contract.cpf_pr_approval, contract.cpf_pr_scheme_start)
    ow = D(basic_wages)
    aw = D(0)
    for item in allowances:
        kind = item["cpf_wage_type"]
        if kind == "ow":
            ow += D(item["amount"])
        elif kind == "aw":
            aw += D(item["amount"])
    if ow < 0 or aw < 0:
        raise ValidationError("CPF wages cannot be negative.")
    ceiling = D(7400 if month.year == 2025 else 8000)
    # Match the cents actually recorded on the payslip, avoiding float noise at $50/$500/$750.
    ow = ow.quantize(D("0.01"), rounding=ROUND_HALF_UP)
    aw = aw.quantize(D("0.01"), rounding=ROUND_HALF_UP)
    subject_ow = min(ow, ceiling)
    subject_aw = aw
    annual_estimate = None
    from payroll.models.models import Payslip
    later = Payslip._base_manager.filter(employee_id=employee, end_date__year=month.year,
        end_date__gte=(month.replace(day=28) + timedelta(days=4)).replace(day=1))
    if any(D(slip.pay_head_data.get("statutory_cpf", {}).get("aw"))
           for slip in later if slip.pay_head_data.get("statutory_cpf")):
        raise ValidationError("Reconcile later Additional-Wage CPF payslips before changing an earlier month's wages.")
    previous = list(Payslip._base_manager.filter(employee_id=employee,
        end_date__year=month.year, end_date__lt=month).order_by("end_date"))
    snapshots = [slip.pay_head_data.get("statutory_cpf") for slip in previous]
    required_keys = {"ow", "aw", "ow_subject", "aw_subject", "employee_rate", "employer_rate", "employee_amount", "employer_amount"}
    if any(snapshot and not required_keys <= snapshot.keys() for snapshot in snapshots):
        raise ValidationError("Reconcile incomplete historical CPF snapshots before generating payroll.")
    had_aw = any(snapshot and D(snapshot["aw"]) for snapshot in snapshots)
    final_month = month.month == 12 or (contract.contract_end_date and contract.contract_end_date <= end)
    employee_adjustment = employer_adjustment = 0
    if aw or had_aw:
        # The annual ledger must be complete; an estimate cannot substitute for
        # bonuses/OW already paid elsewhere or in pre-upgrade payslips.
        joined = employee.employee_work_info.date_joining or contract.contract_start_date
        beginning = max(date(month.year, 1, 1), joined)
        if details.residency_status == "pr":
            beginning = max(beginning, details.pr_effective_date)
        required_months = set(range(beginning.month, month.month))
        recorded_months = {slip.end_date.month for slip in previous}
        if not required_months <= recorded_months or any(not value for value in snapshots):
            raise ValidationError("Reconcile all earlier employment months' OW/AW records before calculating Additional Wages.")
        previous_ow = sum((D(value["ow_subject"]) for value in snapshots), D(0))
        if final_month:
            annual_estimate = previous_ow + subject_ow
        else:
            if contract.cpf_estimate_year != month.year or contract.cpf_annual_ow_estimate is None:
                raise ValidationError("Record this year's estimated annual OW subject to CPF before calculating Additional Wages.")
            annual_estimate = D(contract.cpf_annual_ow_estimate)
        if not previous_ow + subject_ow <= annual_estimate <= 102000:
            raise ValidationError("Annual CPF OW estimate must cover recorded OW and cannot exceed $102,000.")
        remaining = max(D(0), D(102000) - annual_estimate)
        expected_employee = expected_employer = recorded_employee = recorded_employer = 0
        for value in snapshots:
            corrected_aw = min(D(value["aw"]), remaining)
            remaining -= corrected_aw
            emp, employer = contribution_amounts(value["ow_subject"], corrected_aw,
                D(value["employee_rate"]), D(value["employer_rate"]),
                total_wages=D(value["ow"])+D(value["aw"]))
            expected_employee += emp
            expected_employer += employer
            recorded_employee += value["employee_amount"]
            recorded_employer += value["employer_amount"]
        employee_adjustment = expected_employee - recorded_employee
        employer_adjustment = expected_employer - recorded_employer
        if employee_adjustment < 0 or employer_adjustment < 0:
            raise ValidationError("AW ceiling recomputation shows excess CPF. Record a CPF Board refund/reconciliation before regenerating payroll; paid contributions must not be silently reversed.")
        subject_aw = min(aw, remaining)
    base_employee, base_employer = contribution_amounts(subject_ow, subject_aw,
        erate, rrate, total_wages=ow + aw)
    employee_amount = base_employee + employee_adjustment
    employer_amount = base_employer + employer_adjustment
    applied_scheme = "full_both"
    if details.residency_status == "pr" and pr_year < 3:
        applied_scheme = contract.cpf_pr_scheme
        if applied_scheme != "graduated" and month < contract.cpf_pr_scheme_start:
            applied_scheme = "graduated"
    return {
        "version": "sg-cpf-2025-2027-v1", "month": month.isoformat(),
        "residency": details.residency_status, "pr_year": pr_year,
        "scheme": applied_scheme, "configured_pr_scheme": contract.cpf_pr_scheme,
        "ow": float(ow), "aw": float(aw),
        "ow_subject": float(subject_ow), "aw_subject": float(subject_aw),
        "ow_ceiling": float(ceiling), "annual_ow_estimate": float(annual_estimate) if annual_estimate is not None else None,
        "employee_rate": float(erate), "employer_rate": float(rrate),
        "employee_amount": employee_amount, "employer_amount": employer_amount,
        "base_employee_amount": base_employee, "base_employer_amount": base_employer,
        "aw_employee_adjustment": employee_adjustment, "aw_employer_adjustment": employer_adjustment,
        "aw_reconciliation": bool(final_month and had_aw),
    }
