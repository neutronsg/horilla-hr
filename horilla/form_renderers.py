"""Readable select placeholders, applied at render time after form customisation."""

import re

from django.forms import ModelChoiceField, Select
from django.forms.boundfield import BoundField
from django.forms.renderers import DjangoTemplates
from django.utils.translation import gettext as _


def generic_empty_label(label):
    text = str(label or "").strip()
    return (
        not text
        or bool(re.fullmatch(r"[-—–\s]+", text))
        or text.startswith("---Choose")
    )


class LedgerBoundField(BoundField):
    def as_widget(self, widget=None, attrs=None, only_initial=False):
        widget = widget or self.field.widget
        if isinstance(widget, Select):
            has_empty = False
            label = (
                str(self.label or self.name.replace("_", " "))
                .removesuffix(" id")
                .strip()
            )
            label = " ".join(
                word if word.isupper() else word.lower() for word in label.split()
            )
            placeholder = _("Select %(label)s") % {"label": label}
            if hasattr(self.field, "empty_label"):
                has_empty = self.field.empty_label is not None
                # A None label intentionally removes the empty option on required selects.
                if self.field.empty_label is not None and generic_empty_label(
                    self.field.empty_label
                ):
                    self.field.empty_label = placeholder
            if not isinstance(self.field, ModelChoiceField) and hasattr(
                widget, "choices"
            ):
                # django-filter's copied widget can retain a separate choice
                # iterator. Normalise its rendered label too, without changing
                # validation choices or the value posted for the empty option.
                choices = list(widget.choices)
                has_empty = bool(choices and choices[0][0] == "")
                if (
                    choices
                    and choices[0][0] == ""
                    and generic_empty_label(choices[0][1])
                ):
                    widget.choices = [("", placeholder), *choices[1:]]
            if has_empty and generic_empty_label(widget.attrs.get("data-placeholder")):
                widget.attrs["data-placeholder"] = placeholder
        return super().as_widget(widget, attrs, only_initial)


class LedgerFormRenderer(DjangoTemplates):
    bound_field_class = LedgerBoundField
