"""Experimental. The timeline contract: one stream of moments per person and per record.

A project that holds several parts shows, on a person's page and on a
record's page (an order, a ticket, a deal), what happened to them in every
part: a paid order, a closed ticket, a call a CRM logged. Add
``"karni.timeline"`` to ``INSTALLED_APPS`` next to ``karni.people`` and
``karni.outbox``. Entries are written two ways::

    # by hand, for what is not a family event (a call, a note, a meeting)
    from karni import timeline

    timeline.record(kind="crm.call", title="Called about the renewal",
                    person=contact, subjects=[deal], body=notes)

    # from a family event, by declaring a title in <app>/events.py
    declare("helpdesk.ticket.closed", fields={"ticket": "...", "subject": "..."},
            person="person", timeline="Ticket closed: {subject}")

and read through ``GET /api/timeline/?person=<id>`` (or ``?organisation=``,
``?subject=<app_label.model>:<id>``), where an entry shows only to a caller
who may read its person and every record it is linked to
(:mod:`karni.timeline.api`, :mod:`karni.timeline.access`).

What is here: :func:`record`, the entries from declared events
(:mod:`karni.timeline.subscribers`), :func:`prune` with
``KARNI_TIMELINE_RETENTION_DAYS``, the API, the admin, and the erase hook
of the people contract. The contract is versioned: :data:`CONTRACT`.

Override / escape hatches: the ``timeline=`` option per event (a title
template, or a mapping with ``title``, ``body``, ``subjects`` and ``kind``),
``record()`` by hand, ``KARNI_TIMELINE_FROM_EVENTS``,
``KARNI_TIMELINE_VISIBILITY`` and ``KARNI_TIMELINE_API``. See
docs/timeline.md.

The names are imported lazily (PEP 562): this package is imported while the
app registry is still loading, before its models exist.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from karni.timeline.services import (
        TimelineOption,
        installed,
        live_person,
        money_text,
        parse_option,
        prune,
        record,
        render,
        skip_when,
        skipped,
        unskip,
        write_from_event,
    )
    from karni.timeline.subscribers import connect, disconnect

#: Experimental. The version of the timeline contract. A breaking change raises it.
CONTRACT: Final = 1

__all__ = [
    "CONTRACT",
    "TimelineOption",
    "connect",
    "disconnect",
    "installed",
    "live_person",
    "money_text",
    "parse_option",
    "prune",
    "record",
    "render",
    "skip_when",
    "skipped",
    "unskip",
    "write_from_event",
]

_LAZY: Final[dict[str, str]] = {
    **{
        name: "karni.timeline.services"
        for name in (
            "TimelineOption",
            "installed",
            "live_person",
            "money_text",
            "parse_option",
            "prune",
            "record",
            "render",
            "skip_when",
            "skipped",
            "unskip",
            "write_from_event",
        )
    },
    "connect": "karni.timeline.subscribers",
    "disconnect": "karni.timeline.subscribers",
}


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(module), name)


def __dir__() -> list[str]:
    return sorted([*__all__, *globals()])
