"""Experimental. The preferences contract: the project's details and the settings parts declare.

A business changes these without code, on one Settings page: its details
(name, legal name, address, phone, contact email, sender, logo, time zone,
language, currency display), one section per installed part, a switch per
connection and a switch per email. Add ``"karni.preferences"`` to
``INSTALLED_APPS`` (``features: {preferences: true}`` in karni.yaml, or a
recipe whose ``requires`` names ``preferences``) and run migrate.

A part declares, in its own app::

    # <app>/preferences.py
    from pydantic import Field

    from karni import preferences


    @preferences.section("bookings", title="Bookings")
    class BookingPreferences(preferences.Section):
        refund_notice_hours: int = Field(0, ge=0, le=720, description="...")


    # <app>/connections.py
    preferences.connection(
        "bookings.family_events", needs=["events"], default=True, describe="..."
    )

and reads with one call and a typed default, installed or not::

    preferences.value("bookings.refund_notice_hours", 0)
    preferences.active("bookings.family_events")

What is here: :mod:`~karni.preferences.registry` (sections, connections,
email kinds), :mod:`~karni.preferences.services` (read, change, locks,
the per-request cache), :mod:`~karni.preferences.models` (Details,
SectionValue, Switch, all audited), the API behind the Settings page
(``/api/preferences/``, :mod:`~karni.preferences.api`), the admin and the
system checks (``E320`` to ``E322``). The contract is versioned: :data:`CONTRACT`.

Override / escape hatches: ``KARNI_PREFERENCES_LOCKED`` (a value the
deployment fixes, shown read only), ``KARNI_PREFERENCES_DEFAULTS`` (a value
the deployment starts with), ``KARNI_PREFERENCES_API`` and
:func:`override` in tests. See docs/preferences.md.

The names are imported lazily (PEP 562): this package is imported while the
app registry is still loading, before its models exist.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from karni.preferences.registry import (
        Connection,
        EmailKind,
        Section,
        SectionSpec,
        connection,
        connections,
        email,
        emails,
        section,
        sections,
        unregister,
    )
    from karni.preferences.services import (
        PreferenceRefused,
        active,
        can_change,
        details,
        email_on,
        get,
        installed,
        override,
        save_details,
        save_section,
        sender,
        switch,
        value,
    )

#: The version of the preferences contract. A breaking change raises it.
CONTRACT: Final = 1

__all__ = [
    "CONTRACT",
    "Connection",
    "EmailKind",
    "PreferenceRefused",
    "Section",
    "SectionSpec",
    "active",
    "can_change",
    "connection",
    "connections",
    "details",
    "email",
    "email_on",
    "emails",
    "get",
    "installed",
    "override",
    "save_details",
    "save_section",
    "section",
    "sections",
    "sender",
    "switch",
    "unregister",
    "value",
]

_REGISTRY: Final = (
    "Connection",
    "EmailKind",
    "Section",
    "SectionSpec",
    "connection",
    "connections",
    "email",
    "emails",
    "section",
    "sections",
    "unregister",
)
_LAZY: Final[dict[str, str]] = {
    **{name: "karni.preferences.registry" for name in _REGISTRY},
    **{
        name: "karni.preferences.services"
        for name in __all__
        if name not in _REGISTRY and name != "CONTRACT"
    },
}


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(module), name)


def __dir__() -> list[str]:
    return sorted([*__all__, *globals()])
