from django.db import migrations, models


def preserve_annual_policy(apps, schema_editor):
    LeaveType = apps.get_model("leave", "LeaveType")
    LeaveType.objects.filter(auto_annual_leave=True).update(auto_leave_policy="annual")


class Migration(migrations.Migration):
    dependencies = [("leave", "0018_auto_annual_leave")]

    operations = [
        migrations.AddField(
            model_name="leavetype",
            name="auto_leave_policy",
            field=models.CharField(
                max_length=24,
                choices=[
                    ("none", "Manual"),
                    ("annual", "Annual leave"),
                    ("outpatient_sick", "Outpatient sick leave"),
                    ("hospitalisation", "Hospitalisation leave"),
                ],
                default="none",
                verbose_name="Automatic Leave Policy",
                help_text="Use MOM service-based entitlement for this paid leave type.",
            ),
        ),
        migrations.RunPython(preserve_annual_policy, migrations.RunPython.noop),
    ]
