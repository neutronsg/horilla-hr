from django.db import migrations, models


def allow_past_leave_requests(apps, schema_editor):
    restriction = apps.get_model("leave", "EmployeePastLeaveRestrict")
    restriction.objects.all().update(enabled=False)


class Migration(migrations.Migration):
    dependencies = [
        ("leave", "0007_alter_historicalleaverequest_reject_reason_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="employeepastleaverestrict",
            name="enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            allow_past_leave_requests,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
