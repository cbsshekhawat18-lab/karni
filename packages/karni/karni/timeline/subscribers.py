"""Experimental. The core subscriber that turns declared family events into timeline entries.

:func:`connect` subscribes once to every declared event (each version) whose
declaration names a timeline title (``declare(..., timeline=...)``). Each
subscriber is named ``karni.timeline:<event>@v<version>`` in the outbox, so
its deliveries show in the admin and in ``karni check``'s events listing.
``TimelineConfig.ready()`` calls it after every app's ``events.py`` is
imported. Call it again after declaring an event later (a test, a shell): it
adds what is missing and keeps the rest.

Nothing is subscribed while ``karni.outbox`` is not installed (``karni.W460``
says so): a subscriber without the outbox would make every publish of the
event fail.

Override / escape hatch: ``KARNI_TIMELINE_FROM_EVENTS = False`` subscribes
nothing (write entries with :func:`karni.timeline.record` in a subscriber of
your own), and :func:`disconnect` removes them.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Final

from django.conf import settings

if TYPE_CHECKING:
    from karni.outbox.bus import Declaration, Event, Registry

__all__ = ["PREFIX", "connect", "disconnect", "subscriber_name"]

#: The start of every timeline subscriber's name.
PREFIX: Final = "karni.timeline:"


def subscriber_name(name: str, version: int) -> str:
    """The outbox name of the timeline subscriber of ``name`` at ``version``."""
    return f"{PREFIX}{name}@v{version}"


def _writer(name: str, version: int, registry: Registry) -> Callable[[Event], Any]:
    """The function a delivery calls: it reads the declaration when the event arrives."""

    def write(event: Event) -> Any:
        from karni.timeline.services import write_from_event

        declaration = registry.declaration(name, version)
        if declaration is None or declaration.timeline is None:
            return None
        return write_from_event(event, declaration)

    write.__qualname__ = f"write_{name.replace('.', '_')}_v{version}"
    return write


def _wanted(registry: Registry) -> list[Declaration]:
    from karni.outbox.delivery import outbox_installed
    from karni.timeline.services import parse_option

    if not outbox_installed() or not getattr(settings, "KARNI_TIMELINE_FROM_EVENTS", True):
        return []
    found = []
    for declaration in registry.declarations():
        if declaration.timeline is None:
            continue
        try:
            parse_option(declaration)
        except (ValueError, TypeError):
            continue  # karni.E460 reports it at startup
        found.append(declaration)
    return found


def connect(registry: Registry | None = None) -> list[str]:
    """Subscribe to every declared event with ``timeline=``. Returns the names added."""
    from karni.outbox.bus import Subscriber
    from karni.outbox.bus import registry as default

    target = registry if registry is not None else default
    added: list[str] = []
    for declaration in _wanted(target):
        name = subscriber_name(declaration.name, declaration.version)
        if target.subscriber(name) is not None:
            continue
        target.add_subscriber(
            Subscriber(
                event=declaration.name,
                version=declaration.version,
                name=name,
                func=_writer(declaration.name, declaration.version, target),
                source=__name__,
            )
        )
        added.append(name)
    return added


def disconnect(registry: Registry | None = None) -> list[str]:
    """Remove every timeline subscriber. Returns the names removed."""
    from karni.outbox.bus import registry as default

    target = registry if registry is not None else default
    names = [s.name for s in target.subscribers() if s.name.startswith(PREFIX)]
    for name in names:
        target.remove_subscriber(name)
    return names
