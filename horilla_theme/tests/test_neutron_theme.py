"""Neutron default theme migration and company theme variables."""

import importlib
from types import SimpleNamespace

from django.apps import apps
from django.test import SimpleTestCase, TestCase

from horilla_theme.models import THEMES_DATA, HorillaColorTheme
from horilla_theme.templatetags.neutron_ui import neutron_theme_vars

migration = importlib.import_module("horilla_theme.migrations.0002_neutron_default_theme")


class NeutronDefaultMigrationTests(TestCase):
    def setUp(self):
        HorillaColorTheme.objects.all().delete()
        coral = dict(THEMES_DATA[0])
        coral["is_default"] = True
        self.coral = HorillaColorTheme.objects.create(**coral)

    def test_stock_coral_default_becomes_neutron(self):
        migration.add_neutron_theme(apps, None)
        self.assertEqual(HorillaColorTheme.objects.get(is_default=True).name, migration.NEUTRON)

    def test_edited_coral_default_is_kept(self):
        self.coral.primary_600 = "#123456"
        self.coral.save()
        migration.add_neutron_theme(apps, None)
        self.assertEqual(HorillaColorTheme.objects.get(is_default=True).pk, self.coral.pk)
        self.assertTrue(HorillaColorTheme.objects.filter(name=migration.NEUTRON).exists())

    def test_reverse_restores_coral(self):
        migration.add_neutron_theme(apps, None)
        migration.restore_stock_default(apps, None)
        self.assertEqual(HorillaColorTheme.objects.get(is_default=True).pk, self.coral.pk)


class ThemeVariablesTests(SimpleTestCase):
    def test_company_theme_overrides_primary_scale(self):
        forest = next(theme for theme in THEMES_DATA if theme["name"] == "Forest Green Theme")
        css = neutron_theme_vars(SimpleNamespace(**forest))
        self.assertIn("--primary-600:#22c55e;", css)
        self.assertIn("--primary-50:#f0fdf4;", css)

    def test_values_that_are_not_hex_are_skipped(self):
        css = neutron_theme_vars(SimpleNamespace(primary_600="red;}</style><script>", primary_700="#041778"))
        self.assertNotIn("script", css)
        self.assertIn("--primary-700:#041778;", css)

    def test_no_theme_emits_nothing(self):
        self.assertEqual(neutron_theme_vars(None), "")
