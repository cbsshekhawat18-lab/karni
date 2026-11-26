"""System checks of the timeline: its people app, its option, its outbox.

* ``karni.E461``: ``karni.timeline`` is installed without ``karni.people``.
* ``karni.E460``: a declared event's ``timeline=`` option is malformed or
  names a field the event does not declare.
* ``karni.W460``: events declare ``timeline=`` and ``karni.outbox`` is not
  installed, so no entry is written from them.

Registered when ``karni.timeline`` is installed (its ``ready()``).
"""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.core import checks

from karni.exceptions import KarniError, check_error, check_warning

__all__ = ["check_timeline"]


@checks.register()
def check_timeline(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E460 / E461 / W460 (see the module docstring)."""
    from django.conf import settings

    from karni.outbox.bus import registry
    from karni.outbox.delivery import outbox_installed
    from karni.timeline.services import parse_option

    if not apps.is_installed("karni.timeline"):
        return []
    messages: list[checks.CheckMessage] = []
    if not apps.is_installed("karni.people"):
        messages.append(
            check_error(
                "E461",
                "'karni.timeline' is installed without 'karni.people': every entry may point "
                "at a person.",
                hint="Set KARNI_PEOPLE = True above karni_settings(globals()), or add "
                "'karni.people' to INSTALLED_APPS, and run migrate.",
                obj="settings.INSTALLED_APPS",
            )
        )
    declared = [d for d in registry.declarations() if d.timeline is not None]
    for declaration in declared:
        try:
            parse_option(declaration)
        except KarniError as exc:
            messages.append(
                check_error(
                    "E460",
                    exc.message,
                    hint="Fix the timeline= option of this declare() in "
                    f"{declaration.source or 'its events.py'}.",
                    obj=declaration.name,
                )
            )
    if (
        declared
        and not outbox_installed()
        and getattr(settings, "KARNI_TIMELINE_FROM_EVENTS", True)
    ):
        names = ", ".join(sorted({d.name for d in declared}))
        messages.append(
            check_warning(
                "W460",
                f"Events declare a timeline title ({names}) and 'karni.outbox' is not in "
                "INSTALLED_APPS, so no timeline entry is written from them.",
                hint="Add 'karni.outbox' to INSTALLED_APPS and run migrate, or set "
                "KARNI_TIMELINE_FROM_EVENTS = False to write entries with record() only.",
                obj="settings.INSTALLED_APPS",
            )
        )
    return messages
