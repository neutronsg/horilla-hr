"""Date-based annual leave entitlement calculations.

This module is deliberately independent of Django so that the arithmetic can be
checked without a database or a running scheduler.
"""

import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP


@dataclass(frozen=True)
class AnnualEntitlement:
    service_year_start: date
    eligible_date: date
    completed_months: int
    annual_days: int
    earned_days: int


def add_months(start: date, months: int) -> date:
    """Add calendar months, clipping dates such as 31 January to month end."""
    month_index = start.year * 12 + start.month - 1 + months
    year, month_zero_based = divmod(month_index, 12)
    month = month_zero_based + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def completed_months(start: date, last_day: date, excluded_days: float = 0) -> int:
    """Count completed calendar months through ``last_day`` (inclusive).

    MOM excludes periods of approved unpaid leave from service used for annual
    leave. Subtracting those days before counting complete months also matches
    MOM's example of four unpaid days over January–April yielding three months.
    """
    exclusive_end = datetime.combine(last_day + timedelta(days=1), time.min) - timedelta(
        days=excluded_days
    )
    if exclusive_end <= datetime.combine(start, time.min):
        return 0
    candidate = (exclusive_end.year - start.year) * 12 + (
        exclusive_end.month - start.month
    )
    if datetime.combine(add_months(start, candidate), time.min) > exclusive_end:
        candidate -= 1
    return max(0, candidate)


def service_year_start(joining_date: date, as_of: date) -> date:
    """Return the start of the service year containing ``as_of``."""
    anniversary = add_months(joining_date, (as_of.year - joining_date.year) * 12)
    if anniversary > as_of:
        anniversary = add_months(joining_date, (as_of.year - joining_date.year - 1) * 12)
    return anniversary


def calculate_entitlement(
    joining_date: date,
    as_of: date,
    *,
    configured_annual_days: int,
    employment_end_date: date | None = None,
    unpaid_days_in_service_year: float = 0,
) -> AnnualEntitlement:
    """Calculate earned whole days for the employee's current service year.

    The contract end date caps *earned* service; a future end date does not
    advance the balance. The leave type supplies annual days from year one;
    MOM's service-year minimum applies if the configured value is lower.
    """
    if configured_annual_days < 0 or unpaid_days_in_service_year < 0:
        raise ValueError("Annual and unpaid days must be non-negative")

    effective_date = min(as_of, employment_end_date) if employment_end_date else as_of
    eligible_date = add_months(joining_date, 3)
    if effective_date < joining_date:
        return AnnualEntitlement(joining_date, eligible_date, 0, 0, 0)

    year_start = service_year_start(joining_date, effective_date)
    completed_years = year_start.year - joining_date.year
    annual_days = max(configured_annual_days, min(7 + completed_years, 14))
    months = min(
        12,
        completed_months(year_start, effective_date, unpaid_days_in_service_year),
    )
    # The last day of month three completes three months of service (for
    # example, 1 January through 31 March). Leave can be booked from the next
    # day, but a contract ending today has already earned its pro-rated days.
    earned_days = (
        int(
            (Decimal(months) * Decimal(annual_days) / Decimal(12)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        if months >= 3
        else 0
    )
    return AnnualEntitlement(
        year_start, eligible_date, months, annual_days, earned_days
    )
