"""Experimental. What happens to people and organisations, as signals any app can receive.

Every family event of the people contract is published from this module, by
:func:`publish`, inside the transaction of the change it reports::

    from django.dispatch import receiver
    from karni.people.events import person_merged


    @receiver(person_merged)
    def follow(sender, payload, subject, **kwargs):
        kept, removed = payload["kept"], payload["removed"]

======================================  =================================  =================
Event                                   When                               Declared fields
======================================  =================================  =================
``people.person.created``               any part creates a person          ``source``
``people.person.linked``                an account is linked (verified)    ``user``
``people.person.merged``                two people became one              ``kept``, ``removed``
``people.person.erased``                a person's data was erased         none
``people.organisation.created``         any part creates an organisation   ``source``
``people.organisation.merged``          two organisations became one       ``kept``, ``removed``
======================================  =================================  =================

``payload`` holds ids and values only, never model instances: the common
fields (``id``, ``name``, ``version``, ``occurred_at``, ``actor``,
``person``, ``subject`` as ``{"model", "id"}``, ``request_id``) and the
declared ones. ``subject`` is the row itself, for a receiver in the same
process. A receiver runs inside the publisher's transaction: raising undoes
the change.

Every event is also declared on the family event bus (:mod:`karni.events`)
when this module is imported, and :func:`publish` publishes it there first,
so a part in another app subscribes with ``@subscribe("people.person.merged")``
and gets the delivery after the commit, in its own transaction.

Override / escape hatch: the signals are plain :class:`django.dispatch.Signal`
objects, for a receiver that must run inside the publisher's transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from django.db import models
from django.dispatch import Signal

from karni.exceptions import KarniValueError

__all__ = [
    "EVENTS",
    "EventSpec",
    "declare_all",
    "organisation_created",
    "organisation_merged",
    "person_created",
    "person_erased",
    "person_linked",
    "person_merged",
    "publish",
    "signal_for",
]

#: Any part created a person: ``payload["source"]``.
person_created = Signal()
#: An account was linked to a person once its email was verified: ``payload["user"]``.
person_linked = Signal()
#: Two people became one: ``payload["kept"]`` and ``payload["removed"]``.
person_merged = Signal()
#: A person's data was erased on request.
person_erased = Signal()
#: Any part created an organisation: ``payload["source"]``.
organisation_created = Signal()
#: Two organisations became one: ``payload["kept"]`` and ``payload["removed"]``.
organisation_merged = Signal()


@dataclass(frozen=True)
class EventSpec:
    """Experimental. One declared event: its signal, version, fields and person.

    ``fields`` maps each payload field to what it holds. ``person`` says where
    the person the event is about comes from: ``"person"`` (``publish``'s
    ``person=``), a declared field (``"kept"``), or ``None`` for an event
    about an organisation. ``timeline`` is the title of the timeline entry
    the event writes (:mod:`karni.timeline`), or ``None`` for none. The
    names and arguments are those of the family bus's ``declare()``, so
    :func:`declare_all` hands them over unchanged.
    """

    name: str
    signal: Signal
    version: int
    fields: Mapping[str, str]
    person: str | None
    describe: str
    timeline: str | None = None


_SOURCE = {"source": "the app label of the part that created it"}
_MERGED = {"kept": "the id of the record that stays", "removed": "the id of the merged record"}

#: Experimental. Every event of the people contract, by name.
EVENTS: Final[dict[str, EventSpec]] = {
    spec.name: spec
    for spec in (
        EventSpec(
            "people.person.created",
            person_created,
            1,
            _SOURCE,
            "person",
            "A part created a person.",
        ),
        EventSpec(
            "people.person.linked",
            person_linked,
            1,
            {"user": "the id of the account linked to the person"},
            "person",
            "An account was linked to a person once its email was verified.",
            "Account linked",
        ),
        EventSpec(
            "people.person.merged",
            person_merged,
            1,
            _MERGED,
            "kept",
            "Two people became one.",
            "Merged with a duplicate record",
        ),
        EventSpec(
            "people.person.erased", person_erased, 1, {}, "person", "A person's data was erased."
        ),
        EventSpec(
            "people.organisation.created",
            organisation_created,
            1,
            _SOURCE,
            None,
            "A part created an organisation.",
        ),
        EventSpec(
            "people.organisation.merged",
            organisation_merged,
            1,
            _MERGED,
            None,
            "Two organisations became one.",
            "Merged with a duplicate record",
        ),
    )
}


def declare_all(declare: Callable[..., Any]) -> None:
    """Experimental. Call ``declare(name, version=, fields=, person=, describe=)`` for each event.

    What hands the people events to a family event bus: pass its ``declare``.
    An event with a timeline title gets ``timeline=`` too.
    """
    for spec in EVENTS.values():
        options: dict[str, Any] = {
            "version": spec.version,
            "fields": dict(spec.fields),
            "person": spec.person,
            "describe": spec.describe,
        }
        if spec.timeline is not None:
            options["timeline"] = spec.timeline
        declare(spec.name, **options)


def signal_for(name: str) -> Signal:
    """Experimental. The signal of the event ``name`` (``E259`` for a name not declared here)."""
    spec = EVENTS.get(name)
    if spec is None:
        raise KarniValueError(
            f"{name!r} is not an event of the people contract. Events: {', '.join(EVENTS)}.",
            code="E259",
        )
    return spec.signal


def _value(value: Any) -> Any:
    if isinstance(value, models.Model):
        return str(value.pk)
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def publish(
    name: str, *, subject: models.Model, person: models.Model | None = None, **fields: Any
) -> dict[str, Any]:
    """Experimental. Publish the event ``name`` about ``subject`` and return its payload.

    The event goes to the family bus first (:func:`karni.events.publish`:
    an outbox row in the current transaction when ``karni.outbox`` is
    installed, delivered to subscribers after the commit), then its signal is
    sent with the same payload, so a receiver and a subscriber see one event
    id. ``fields`` must be exactly the event's declared fields (``E259``); a
    row among them is sent as its key.
    """
    from karni import events as bus

    spec = EVENTS.get(name)
    if spec is None or set(fields) != set(spec.fields):
        declared = ", ".join(spec.fields) if spec is not None else "none"
        raise KarniValueError(
            f"people event {name!r} takes the fields {declared}, got "
            f"{', '.join(sorted(fields)) or 'none'}.",
            code="E259",
        )
    event = bus.publish(
        name,
        subject=subject,
        person=person,
        version=spec.version,
        **{key: _value(value) for key, value in fields.items()},
    )
    payload = event.payload
    spec.signal.send(sender=type(subject), payload=payload, subject=subject)
    return payload


def _declare() -> None:
    from karni import events as bus

    declare_all(bus.declare)


# Every people event is declared on the family bus when this module is imported
# (karni.events.autodiscover imports it at startup).
_declare()
