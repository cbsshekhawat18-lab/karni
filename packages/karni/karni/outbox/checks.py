"""System checks of the family event bus, and the listing ``karni check`` prints.

Registered by :mod:`karni.checks` whether or not ``karni.outbox`` is
installed, so a subscriber in a project without the outbox is reported:

* ``karni.E451``: subscribers exist and ``karni.outbox`` is not installed.
* ``karni.E455``: ``KARNI_EVENTS_DISPATCHER`` cannot be imported or called.
* ``karni.W450``: a subscriber reads a version its declared event does not
  have (the publisher moved on, or the subscriber went first).

A subscriber to an event nothing declares is not a problem: the part that
publishes it is not installed, and the subscriber is never called.
:func:`event_listing` is what ``manage.py karni_check`` prints.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core import checks

from karni.exceptions import KarniError, check_error, check_warning

__all__ = ["check_event_bus", "event_listing"]


@checks.register()
def check_event_bus(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E451 / E455 / W450: the outbox, the dispatcher and the subscribers' versions."""
    from karni.outbox.bus import registry
    from karni.outbox.delivery import outbox_installed
    from karni.outbox.dispatch import DEFAULT, SETTING, load

    messages: list[checks.CheckMessage] = []
    subscribers = registry.subscribers()
    if subscribers and not outbox_installed():
        names = ", ".join(sorted({s.name for s in subscribers}))
        messages.append(
            check_error(
                "E451",
                f"Family event subscribers exist ({names}) and 'karni.outbox' is not in "
                "INSTALLED_APPS, so nothing could deliver to them.",
                hint="Add 'karni.outbox' to INSTALLED_APPS and run migrate.",
                obj="settings.INSTALLED_APPS",
            )
        )
    path = getattr(settings, SETTING, None) or DEFAULT
    if not callable(path):
        try:
            load(str(path))
        except KarniError as exc:
            messages.append(
                check_error(
                    "E455",
                    exc.message,
                    hint=f"Name a function taking (event_id, *, countdown=0), or remove "
                    f"{SETTING} for the default.",
                    obj=f"settings.{SETTING}",
                )
            )
    for subscriber in subscribers:
        versions = registry.versions(subscriber.event)
        if versions and subscriber.version not in versions:
            messages.append(
                check_warning(
                    "W450",
                    f"{subscriber.name} subscribes to {subscriber.event!r} version "
                    f"{subscriber.version}, and the installed publisher declares version "
                    f"{', '.join(str(v) for v in versions)}. It will receive nothing.",
                    hint=f"Read version {versions[-1]} in the subscriber "
                    f"(@subscribe({subscriber.event!r}, version={versions[-1]})) and adapt it "
                    "to that payload.",
                    obj=subscriber.name,
                )
            )
    return messages


def event_listing() -> list[str]:
    """One line per declared event with its subscribers, then events nothing declares here."""
    from karni.outbox.bus import registry

    lines: list[str] = []
    declared: set[tuple[str, int]] = set()
    for declaration in registry.declarations():
        key = (declaration.name, declaration.version)
        declared.add(key)
        names = [s.name for s in registry.subscribers_of(*key)]
        heard = ", ".join(names) if names else "no subscribers"
        lines.append(f"{declaration.name} v{declaration.version} ({declaration.source}): {heard}")
    waiting: dict[tuple[str, int], list[str]] = {}
    for subscriber in registry.subscribers():
        key = (subscriber.event, subscriber.version)
        if key not in declared:
            waiting.setdefault(key, []).append(subscriber.name)
    for (name, version), names in sorted(waiting.items()):
        lines.append(
            f"{name} v{version} is not declared here (its publisher is not installed): "
            f"{', '.join(names)}"
        )
    return lines
