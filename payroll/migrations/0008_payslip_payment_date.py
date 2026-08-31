from datetime import date, timedelta

from django.db import migrations, models


def default_payment_date(end_date):
    month = end_date.month + 1
    year = end_date.year
    if month == 13:
        month = 1
        year += 1
    payment_date = date(year, month, 6)
    while payment_date.weekday() >= 5:
        payment_date += timedelta(days=1)
    return payment_date


def populate_payment_dates(apps, schema_editor):
    Payslip = apps.get_model("payroll", "Payslip")
    for payslip in Payslip.objects.filter(payment_date__isnull=True).only("id", "end_date"):
        payslip.payment_date = default_payment_date(payslip.end_date)
        payslip.save(update_fields=["payment_date"])


class Migration(migrations.Migration):
    dependencies = [("payroll", "0007_alter_allowance_amount_and_more")]

    operations = [
        migrations.AddField(
            model_name="payslip",
            name="payment_date",
            field=models.DateField(
                blank=True,
                help_text="Actual salary payment date; defaults to the 6th of the following month, moved to Monday when it falls on a weekend.",
                null=True,
                verbose_name="Payment Date",
            ),
        ),
        migrations.RunPython(populate_payment_dates, migrations.RunPython.noop),
    ]
