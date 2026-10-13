from django.db import migrations


def remove_legacy_permissions(apps, schema_editor):
    # Earlier generic export-permission syncs created entries for these models.
    # All Singapore subsections now reuse HR/Admin employee access, and generic
    # exports of these models are prohibited regardless of permission grants.
    Permission = apps.get_model("auth", "Permission")
    Permission.objects.using(schema_editor.connection.alias).filter(
        content_type__app_label="employee",
        content_type__model__in=(
            "singaporeemployeedetails", "singaporedetailsaudit", "singaporecontributionprofile",
        ),
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("employee", "0009_singapore_hr_employee_access")]

    operations = [
        migrations.RunPython(remove_legacy_permissions, migrations.RunPython.noop),
    ]
