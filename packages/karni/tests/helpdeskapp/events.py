"""The help desk's family events: each names a timeline title, so it lands on the timeline."""

from __future__ import annotations

from karni.events import declare

declare(
    "helpdeskapp.ticket.opened",
    version=1,
    fields={"ticket": "the ticket's id", "topic": "what the ticket is about"},
    person="person",
    timeline="Ticket opened: {topic}",
    describe="A person opened a support ticket.",
)
declare(
    "helpdeskapp.ticket.closed",
    version=1,
    fields={
        "ticket": "the ticket's id",
        "topic": "what the ticket is about",
        "minutes": "minutes the ticket was open",
    },
    person="person",
    timeline={
        "title": "Ticket closed: {topic}",
        "body": "Closed after {minutes} minutes.",
        "kind": "helpdeskapp.ticket.closed",
    },
    describe="Staff closed a support ticket.",
)
