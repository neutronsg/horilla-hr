"""
scheduler.py

This module is used to register scheduled tasks
"""

import json
import calendar
import logging
import sys
from datetime import date, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from django.core.exceptions import ValidationError
from django.utils import timezone

from payroll.methods.methods import calculate_employer_contribution, save_payslip
from payroll.views.component_views import payroll_calculation

from .models.models import Contract, Payslip

logger = logging.getLogger(__name__)


def previous_calendar_month(run_date):
    period_end = run_date.replace(day=1) - timedelta(days=1)
    return period_end.replace(day=1), period_end


def expire_contract():
    """
    Finds all active contracts whose end date is earlier than the current date
    and updates their status to "expired".
    """
    Contract.objects.filter(
        contract_status="active", contract_end_date__lt=date.today()
    ).update(contract_status="expired")
    return


def generate_payslip(date, companies, all):
    """Generate payslip for previous month"""

    from employee.models import Employee

    employees = Employee.objects.none()
    # Get all employees with in the companies
    if all == True:
        employees = employees | Employee.objects.filter(
            employee_work_info__company_id__isnull=True
        )
    if companies:
        for company in companies:
            employees = employees | Employee.objects.filter(
                employee_work_info__company_id=company
            )

    # Historical payroll includes staff who left during the previous month.
    period_start, period_end = previous_calendar_month(date)
    from payroll.contracts import select_payroll_contract
    from payroll.calendar import employment_period
    # Payslip creation
    for employee in employees.distinct():
        try:
            contract = select_payroll_contract(employee, period_start, period_end)
        except ValidationError:
            logger.exception("Automatic payroll contract validation failed for employee %s", employee.pk)
            continue
        if contract is None:
            continue
        start_date, end_date = employment_period(employee, contract, period_start, period_end)
        payslip = Payslip.objects.filter(
            employee_id=employee, start_date=start_date, end_date=end_date
        ).first()
        if payslip:
            continue
        try:
            payslip_data = payroll_calculation(employee, period_start, period_end)
        except ValidationError:
            logger.exception("Automatic payroll calculation failed for employee %s", employee.pk)
            continue
        if not payslip_data:
            continue
        payslip_data["payslip"] = payslip
        data = {}
        data["employee"] = employee
        data["start_date"] = payslip_data["start_date"]
        data["end_date"] = payslip_data["end_date"]
        data["status"] = "draft"
        data["contract_wage"] = payslip_data["contract_wage"]
        data["basic_pay"] = payslip_data["basic_pay"]
        data["gross_pay"] = payslip_data["gross_pay"]
        data["deduction"] = payslip_data["total_deductions"]
        data["net_pay"] = payslip_data["net_pay"]
        data["pay_data"] = json.loads(payslip_data["json_data"])
        calculate_employer_contribution(data)
        data["installments"] = payslip_data["installments"]
        try:
            payslip_data["instance"] = save_payslip(**data)
        except ValidationError:
            logger.exception("Automatic payroll save validation failed for employee %s", employee.pk)


def is_last_day_of_month(date):
    next_day = date + timedelta(days=1)
    return next_day.month != date.month


def auto_payslip_generate():
    """
    Generating payslips for active contract employees
    """
    from base.models import Company

    from .models.models import PayslipAutoGenerate

    # from payroll.models import PayslipAutoGenerate
    if PayslipAutoGenerate.objects.filter(auto_generate=True).exists():
        today = timezone.localdate()
        day_today = today.day
        last_day_number = calendar.monthrange(today.year, today.month)[1]
        auto_payslips = PayslipAutoGenerate.objects.filter(auto_generate=True)
        companies = []
        auto_companies = [auto.company_id for auto in auto_payslips]
        for auto in auto_payslips:
            generate_day = auto.generate_day
            if generate_day == "last day":
                if is_last_day_of_month(today):
                    companies.append(auto.company_id)
            else:
                generate_day = int(generate_day)
                if generate_day >= last_day_number and day_today == last_day_number:
                    companies.append(auto.company_id)
                elif generate_day == day_today:
                    companies.append(auto.company_id)

        companies = list(set(companies))  # Remove duplicates
        # Check if 'All company' case exists, i.e., None is in companies
        if companies:
            if None in companies:
                # A company with its own schedule is excluded from the default,
                # but must still run when its own schedule is due today.
                explicit_companies = [company for company in companies if company is not None]
                default_companies = [company for company in Company.objects.all() if company not in auto_companies]
                generate_payslip(date=today, companies=explicit_companies + default_companies, all=True)
            else:
                generate_payslip(date=today, companies=companies, all=False)


if not any(
    cmd in sys.argv
    for cmd in ["makemigrations", "migrate", "compilemessages", "flush", "shell"]
):
    scheduler = BackgroundScheduler()
    scheduler.add_job(expire_contract, "interval", hours=4)
    scheduler.add_job(auto_payslip_generate, "interval", hours=3)
    scheduler.start()
