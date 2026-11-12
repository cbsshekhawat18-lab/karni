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

Override / escape hatch: these are plain :class:`django.dispatch.Signal`
objects. The family event bus (outbox delivery after commit) will publish
from :func:`publish` too, so a receiver written now keeps working.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Final

from django.db import models
from django.dispatch import Signal
from django.utils import timezone

from karni.exceptions import KarniValueError

__all__ = [
    "EVENTS",
    "EventSpec",
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
    """Experimental. One declared event: its signal, version and fields."""

    name: str
    signal: Signal
    version: int
    fields: tuple[str, ...]


#: Experimental. Every event of the people contract, by name.
EVENTS: Final[dict[str, EventSpec]] = {
    spec.name: spec
    for spec in (
        EventSpec("people.person.created", person_created, 1, ("source",)),
        EventSpec("people.person.linked", person_linked, 1, ("user",)),
        EventSpec("people.person.merged", person_merged, 1, ("kept", "removed")),
        EventSpec("people.person.erased", person_erased, 1, ()),
        EventSpec("people.organisation.created", organisation_created, 1, ("source",)),
        EventSpec("people.organisation.merged", organisation_merged, 1, ("kept", "removed")),
    )
}


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
    """Experimental. Send the event ``name`` about ``subject`` and return its payload.

    ``fields`` must be exactly the event's declared fields (``E259``); a row
    among them is sent as its key.
    """
    from karni.middleware import get_current_user
    from karni.tracing import get_request_id

    spec = EVENTS.get(name)
    if spec is None or set(fields) != set(spec.fields):
        declared = ", ".join(spec.fields) if spec is not None else "none"
        raise KarniValueError(
            f"people event {name!r} takes the fields {declared}, got "
            f"{', '.join(sorted(fields)) or 'none'}.",
            code="E259",
        )
    actor = get_current_user()
    payload: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "name": name,
        "version": spec.version,
        "occurred_at": timezone.now().isoformat(),
        "actor": _value(getattr(actor, "pk", None)),
        "person": _value(person.pk) if person is not None else None,
        "subject": {"model": subject._meta.label_lower, "id": str(subject.pk)},
        "request_id": get_request_id() or "",
        **{key: _value(value) for key, value in fields.items()},
    }
    spec.signal.send(sender=type(subject), payload=payload, subject=subject)
    return payload
