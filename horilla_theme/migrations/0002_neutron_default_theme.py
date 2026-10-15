"""
Add the Neutron colour theme and make it the default on existing installs.

Only replaces the stock default (Coral Red). If an administrator already chose
another default theme, or companies have their own CompanyTheme, those choices
are kept. On a fresh database the table is still empty here; the post_migrate
seeding (THEMES_DATA, which now ends with the Neutron default) creates themes.
"""

from django.db import migrations

STOCK_DEFAULT = "Coral Red Theme (Default)"
NEUTRON = "Neutron"
# Frozen copy of horilla_theme.models.NEUTRON_THEME at the time of this migration.
NEUTRON_COLOURS = {
    "description": "Neutron brand: navy primary on cool neutrals",
    "primary_50": "#f7f8fc", "primary_100": "#eef1fb", "primary_200": "#e3e9ff",
    "primary_300": "#cad5fc", "primary_400": "#9cacfa", "primary_500": "#617be3",
    "primary_600": "#051c97", "primary_700": "#041778", "primary_800": "#03125f",
    "primary_900": "#020c40",
    "dark_50": "#e3e6ea", "dark_100": "#5a606b", "dark_200": "#444a55",
    "dark_300": "#22262e", "dark_400": "#5a606b", "dark_500": "#0b0d12",
    "dark_600": "#0b0d12",
    "secondary_50": "#f8fafc", "secondary_100": "#f1f5f9", "secondary_200": "#e2e8f0",
    "secondary_300": "#cbd5e1", "secondary_400": "#e3e9ff", "secondary_500": "#cad5fc",
    "secondary_600": "#051c97", "secondary_700": "#334155", "secondary_800": "#1e293b",
    "secondary_900": "#0f172a",
}


def add_neutron_theme(apps, schema_editor):
    Theme = apps.get_model("horilla_theme", "HorillaColorTheme")
    if not Theme.objects.exists():
        return
    neutron, _ = Theme.objects.get_or_create(
        name=NEUTRON, defaults={**NEUTRON_COLOURS, "is_default": False}
    )
    current = Theme.objects.filter(is_default=True)
    if not current.exists() or set(current.values_list("name", flat=True)) == {STOCK_DEFAULT}:
        current.update(is_default=False)
        Theme.objects.filter(pk=neutron.pk).update(is_default=True)


def restore_stock_default(apps, schema_editor):
    Theme = apps.get_model("horilla_theme", "HorillaColorTheme")
    neutron = Theme.objects.filter(name=NEUTRON, is_default=True).first()
    if neutron:
        neutron.is_default = False
        neutron.save(update_fields=["is_default"])
        Theme.objects.filter(name=STOCK_DEFAULT).update(is_default=True)


class Migration(migrations.Migration):

    dependencies = [
        ("horilla_theme", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(add_neutron_theme, restore_stock_default),
    ]
