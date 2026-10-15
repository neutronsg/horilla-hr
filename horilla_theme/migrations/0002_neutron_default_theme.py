"""
Add the Neutron colour theme and make it the default on existing installs.

Only replaces the stock default (Coral Red) while its name and colours are
unchanged. If an administrator edited that theme, chose another default theme,
or companies have their own CompanyTheme, those choices are kept. On a fresh database the table is still empty here; the post_migrate
seeding (THEMES_DATA, which now ends with the Neutron default) creates themes.
"""

from django.db import migrations

STOCK_DEFAULT = "Coral Red Theme (Default)"
NEUTRON = "Neutron"
# Frozen stock Coral palette (horilla_theme.models.THEMES_DATA[0] before this migration).
STOCK_COLOURS = {
    "primary_50": "#f6f6f6", "primary_100": "#fff5f1", "primary_200": "#fef6f5", "primary_300": "#fcedeb",
    "primary_400": "#fbe5e1", "primary_500": "#f7c8c1", "primary_600": "#e54f38", "primary_700": "#ce4732",
    "primary_800": "#ac3b2a", "primary_900": "#672419", "dark_50": "#e6e6e6", "dark_100": "#a8a8a8",
    "dark_200": "#515151", "dark_300": "#501c14", "dark_400": "#64748b", "dark_500": "#190906",
    "dark_600": "#000000", "secondary_50": "#f8fafc", "secondary_100": "#f1f5f9", "secondary_200": "#e2e8f0",
    "secondary_300": "#cbd5e1", "secondary_400": "#fbe5e1", "secondary_500": "#f7c8c1", "secondary_600": "#e54f38",
    "secondary_700": "#334155", "secondary_800": "#1e293b", "secondary_900": "#0f172a",
}
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


def _is_stock(theme):
    return theme.name == STOCK_DEFAULT and all(
        (getattr(theme, field) or "").lower() == colour for field, colour in STOCK_COLOURS.items()
    )


def add_neutron_theme(apps, schema_editor):
    Theme = apps.get_model("horilla_theme", "HorillaColorTheme")
    if not Theme.objects.exists():
        return
    neutron, _ = Theme.objects.get_or_create(
        name=NEUTRON, defaults={**NEUTRON_COLOURS, "is_default": False}
    )
    current = Theme.objects.filter(is_default=True)
    if not current.exists() or all(_is_stock(theme) for theme in current):
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
