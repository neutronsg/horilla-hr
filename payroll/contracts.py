"""Select the employment contract applicable to the requested payroll period."""

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


def select_payroll_contract(employee, start_date, end_date):
    from payroll.calendar import employment_period
    from payroll.models.models import Contract

    candidates = Contract.objects.filter(
        employee_id=employee,
        contract_status__in=("active", "expired", "terminated"),
        contract_start_date__lte=end_date,
    ).filter(Q(contract_end_date__isnull=True) | Q(contract_end_date__gte=start_date))
    applicable = [
        contract for contract in candidates
        if employment_period(employee, contract, start_date, end_date)[0]
        <= employment_period(employee, contract, start_date, end_date)[1]
    ]
    if len(applicable) > 1:
        raise ValidationError(_(
            "Multiple contracts cover this payroll period. Correct overlapping "
            "contracts or arrange a consolidated calculation for the contract change."
        ))
    return applicable[0] if applicable else None
