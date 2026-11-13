"""Experimental. What ``GET /api/preferences/`` answers: the Settings page.

The shape is the family preferences contract's (``details``, ``sections``,
``connections``, ``emails``), so the page in @karni/ui reads either one.
Until that contract is installed, :mod:`karni_commerce.preferences_seam` keeps
the values; connections are the contract's, so the list here is empty.
"""

from __future__ import annotations

from typing import Any

from karni_commerce import preferences_seam as preferences

__all__ = ["PUBLIC_DETAILS", "detail_fields", "may_open", "page", "public"]

#: The details anyone may read (``GET preferences/public/``).
PUBLIC_DETAILS = (
    "name",
    "legal_name",
    "address",
    "phone",
    "email",
    "time_zone",
    "language",
    "currency",
    "currency_display",
)

_KINDS = {
    "address": "textarea",
    "email": "email",
    "sender_email": "email",
    "reply_to": "email",
    "currency_display": "choice",
}


def detail_fields() -> list[dict[str, Any]]:
    """Each detail as the page draws it: name, label, type, help, choices."""
    found = []
    for name in preferences.DETAIL_FIELDS:
        info = preferences.Details.model_fields[name]
        kind = _KINDS.get(name, "text")
        entry: dict[str, Any] = {
            "name": name,
            "label": name.replace("_", " ").capitalize(),
            "type": kind,
            "help": info.description or "",
        }
        if kind == "choice":
            entry["choices"] = [
                {"value": value, "label": label} for value, label in preferences.CURRENCY_DISPLAYS
            ]
        found.append(entry)
    return found


def may_open(user: Any) -> bool:
    targets = ["details", "emails", *(spec.key for spec in preferences.sections())]
    return any(preferences.can_change(user, target) for target in targets)


def page(user: Any) -> dict[str, Any]:
    """Experimental. The Settings page for ``user``."""
    from karni.mail import kinds

    shown = preferences.details()
    sections = [
        {
            "key": spec.key,
            "title": spec.title,
            "describe": spec.describe,
            "version": spec.version,
            "schema": spec.schema(),
            "values": preferences.get(spec.key).model_dump(mode="json"),
            "defaults": spec.defaults(),
            "locked": sorted(preferences.locked_names(spec.key)),
            "can_change": preferences.can_change(user, spec.key),
        }
        for spec in preferences.sections()
    ]
    emails = [
        {
            "name": kind.name,
            "title": kind.title,
            "describe": kind.describe,
            "audience": kind.audience,
            "transactional": kind.transactional,
            "switchable": kind.switchable,
            "source": kind.name.split(".", 1)[0],
            "default": True,
            "on": preferences.email_on(kind.name),
            "locked": kind.name in preferences.locked_names("emails") or not kind.switchable,
        }
        for kind in kinds()
    ]
    return {
        "contract": 1,
        "details": {
            "values": shown.as_dict(),
            "fields": detail_fields(),
            "locked": sorted(preferences.locked_names("details") | {"currency"}),
            "can_change": preferences.can_change(user, "details"),
        },
        "sections": sections,
        "connections": {"items": [], "can_change": False},
        "emails": {
            "sender": {
                "sender_name": shown.sender_name,
                "sender_email": shown.sender_email,
                "reply_to": shown.reply_to,
                "from": preferences.sender() or "",
            },
            "items": emails,
            "can_change": preferences.can_change(user, "emails"),
        },
    }


def public() -> dict[str, Any]:
    """Experimental. The details any visitor may see."""
    shown = preferences.details().as_dict()
    return {name: shown[name] for name in PUBLIC_DETAILS}
