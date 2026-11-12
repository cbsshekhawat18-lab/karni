"""``{% demo_login as login %}``: the demo login for a template, ``None`` while DEMO_MODE is off."""

from __future__ import annotations

from django import template

from demo import account

register = template.Library()


@register.simple_tag
def demo_login() -> dict[str, object] | None:
    if not account.demo_mode():
        return None
    return {
        "email": account.email(),
        "password": account.password(),
        "hours": account.reset_hours(),
    }
