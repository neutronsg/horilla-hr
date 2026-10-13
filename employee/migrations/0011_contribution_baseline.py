from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("employee", "0010_remove_legacy_singapore_permissions")]
    operations = [
        migrations.AddField(
            model_name="singaporecontributionprofile", name="is_baseline",
            field=models.BooleanField(default=False, editable=False),
        ),
    ]
