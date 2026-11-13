"""``{% demo_info as demo %}``: the demo accounts for a template, ``None`` if demo mode is off."""

from __future__ import annotations

from typing import Any

from django import template

from karni.demo import conf, views

register = template.Library()


@register.simple_tag
def demo_info() -> dict[str, Any] | None:
    """The same dict ``GET /api/demo/`` returns, or ``None`` while ``KARNI_DEMO_MODE`` is off."""
    return views.info() if conf.demo_mode() else None
