"""MOM paid outpatient and hospitalisation leave entitlement in whole days."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from leave.annual_entitlement import add_months, completed_months


MOM_SICK_DAYS = {
    "outpatient_sick": (0, 0, 0, 5, 8, 11, 14),
    "hospitalisation": (0, 0, 0, 15, 30, 45, 60),
}


@dataclass(frozen=True)
class SickEntitlement:
    usage_start: date
    eligible_date: date
    completed_months: int
    annual_days: int
    earned_days: int


def calculate_sick_entitlement(
    joining_date: date,
    as_of: date,
    *,
    policy: str,
    configured_days: int,
    employment_end_date: date | None = None,
) -> SickEntitlement:
    """Return the earned entitlement and the start of the applicable usage window.

    During the first six months, usage since joining counts even across New Year.
    From six completed months onwards, usage resets on 1 January.
    """
    if policy not in MOM_SICK_DAYS:
        raise ValueError("Unknown sick leave policy")
    if configured_days < 0:
        raise ValueError("Sick leave days must be non-negative")

    effective_date = min(as_of, employment_end_date) if employment_end_date else as_of
    eligible_date = add_months(joining_date, 3)
    months = max(0, min(6, completed_months(joining_date, effective_date))) if effective_date >= joining_date else 0
    minimum = MOM_SICK_DAYS[policy]
    annual_days = max(configured_days, minimum[6])
    earned_days = 0
    if effective_date >= eligible_date:
        earned_days = max(
            minimum[months],
            int(
                (Decimal(annual_days) * Decimal(minimum[months]) / Decimal(minimum[6]))
                .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            ),
        )
    usage_start = (
        date(effective_date.year, 1, 1) if months >= 6 else joining_date
    )
    return SickEntitlement(
        usage_start, eligible_date, months, annual_days, earned_days
    )
