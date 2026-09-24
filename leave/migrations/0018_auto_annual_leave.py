from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("leave", "0017_allow_past_leave_requests"),
    ]

    operations = [
        migrations.AddField(
            model_name="leavetype",
            name="auto_annual_leave",
            field=models.BooleanField(
                default=False,
                verbose_name="Auto Calculate Annual Leave",
                help_text=(
                    "Use the assigned leave type's annual days, completed months of "
                    "service and MOM rounding after three months of service."
                ),
            ),
        ),
        migrations.AddField(
            model_name="availableleave",
            name="auto_service_year_start",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="availableleave",
            name="auto_entitlement_days",
            field=models.FloatField(default=0),
        ),
        migrations.AddField(
            model_name="historicalavailableleave",
            name="auto_service_year_start",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="historicalavailableleave",
            name="auto_entitlement_days",
            field=models.FloatField(default=0),
        ),
    ]
