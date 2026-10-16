"""
Local initials avatars.

Replaces the third-party ui-avatars.com service, which received employee,
manager, department and asset names in image URLs on many pages. Accepts the
same query parameters the templates already use (name, background, color),
renders a small SVG and is safe to cache: it only echoes the given name's
initials and reads no data.
"""

import hashlib
import re

from django.http import HttpResponse
from django.utils.html import escape
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

# (background, text) pairs in the Neutron palette; picked deterministically per name.
PALETTE = (
    ("#eef1fb", "#051c97"),
    ("#e5f6f6", "#0b6466"),
    ("#eef1f5", "#334155"),
    ("#f0eefb", "#4a3a96"),
    ("#e8f4ee", "#17603d"),
    ("#fbf2e4", "#875200"),
    ("#f5edf6", "#6b2f73"),
    ("#e9f0fa", "#1d4f91"),
)
_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")
_SPLIT = re.compile(r"[\s+_\-./]+")


def initials(name):
    words = [w for w in _SPLIT.split(name.strip()) if w]
    if not words:
        return "?"
    first = words[0]
    second = words[1][0] if len(words) > 1 else (first[1] if len(first) > 1 else "")
    return (first[0] + second).upper()


def _hex(value):
    match = _HEX.match(value or "")
    return f"#{match.group(1)}" if match else None


@require_GET
@cache_control(public=True, max_age=60 * 60 * 24 * 30)
def initials_avatar(request):
    name = request.GET.get("name", "")[:80]
    digest = int(hashlib.sha1(name.strip().lower().encode()).hexdigest(), 16)
    pal_bg, pal_fg = PALETTE[digest % len(PALETTE)]
    background = _hex(request.GET.get("background")) or pal_bg
    color = _hex(request.GET.get("color")) or (pal_fg if background == pal_bg else "#22262e")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">'
        f'<rect width="64" height="64" fill="{background}"/>'
        '<text x="32" y="32" dy=".35em" text-anchor="middle" '
        'font-family="Geist, Inter, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif" '
        f'font-size="25" font-weight="600" fill="{color}">{escape(initials(name))}</text></svg>'
    )
    return HttpResponse(svg, content_type="image/svg+xml")
