"""Apply recorded statutory exemptions regardless of component targeting."""


def eligible_deductions(queryset, employee):
    from django.db.models import Q
    from payroll.models.models import Contract

    contract = Contract.objects.filter(employee_id=employee, contract_status="active").first()
    if contract and contract.salary_structure_id:
        # An explicitly selected structure is HR's recurring deduction policy.
        # Keep separately recorded advances, installments and one-off items.
        queryset = queryset.filter(
            Q(pk__in=contract.salary_structure_id.deductions.values("pk"))
            | Q(only_show_under_employee=True)
            | Q(is_installment=True)
            | Q(one_time_date__isnull=False)
            | Q(update_compensation__isnull=False)
        )
    if contract and contract.cpf_exempt:
        queryset = queryset.exclude(statutory_type__in=("cpf", "cdac", "ecf", "sinda"))
    return queryset
