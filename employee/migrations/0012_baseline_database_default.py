from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("employee", "0011_contribution_baseline")]
    operations = [
        migrations.AlterField(
            model_name="singaporecontributionprofile", name="is_baseline",
            field=models.BooleanField(default=False, db_default=False, editable=False),
        ),
    ]
