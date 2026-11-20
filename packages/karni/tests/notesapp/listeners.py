"""Subscribers by name: no import of the help desk, which may not be installed."""

from __future__ import annotations

from typing import Any

from django.db.models import F

from karni.events import Event, once, subscribe
from karni.tracing import get_request_id
from tests.notesapp.models import Note, Tally

#: Tests set ``fail`` to make the next deliveries raise (after writing a note).
behaviour: dict[str, Any] = {"fail": 0}
#: Calls of the subscriber to an event no installed app declares.
never: list[str] = []


@subscribe("desk.ticket.closed", version=1)
def write_note(event: Event) -> None:
    """One note per event: the unique event id keeps a redelivery from writing twice."""
    Note.objects.get_or_create(
        event_id=event.id,
        defaults={
            "ticket": event["ticket"],
            "person": event.person or "",
            "request_id": get_request_id() or "",
        },
    )
    if behaviour["fail"]:
        behaviour["fail"] -= 1
        raise RuntimeError("the notes service is down")


@subscribe("desk.ticket.closed", version=1, name="notes.tally_closures")
def tally_closures(event: Event) -> None:
    """A counter has no unique key of its own, so once() guards it."""
    if once(event, "tally"):
        tally, _ = Tally.objects.get_or_create(name="closed")
        Tally.objects.filter(pk=tally.pk).update(count=F("count") + 1)


@subscribe("absent.thing.happened", version=1)
def never_called(event: Event) -> None:
    """No installed app declares or publishes this event: nothing calls it, nothing fails."""
    never.append(event.id)
