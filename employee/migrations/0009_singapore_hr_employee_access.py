from django.db import migrations
from django.utils.translation import gettext_lazy as _


def remove_separate_permissions(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Permission.objects.using(schema_editor.connection.alias).filter(
        content_type__app_label="employee",
        content_type__model="singaporeemployeedetails",
        codename__in=("view_singaporeemployeedetails", "change_singaporeemployeedetails"),
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("employee", "0008_singaporecontributionprofile_fund_selection_and_more")]

    operations = [
        migrations.AlterModelOptions(
            name="singaporeemployeedetails",
            options={
                "default_permissions": (),
                "verbose_name": _("Singapore employment details"),
                "verbose_name_plural": _("Singapore employment details"),
            },
        ),
        migrations.RunPython(remove_separate_permissions, migrations.RunPython.noop),
    ]
