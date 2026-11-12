"""The help desk's family events: declared here, published by services.close."""

from __future__ import annotations

from karni.events import declare

declare(
    "desk.ticket.closed",
    version=1,
    fields={"ticket": "the ticket's id", "minutes": "minutes it was open, a whole number"},
    person="person",
    timeline="Ticket {ticket} closed",
    describe="Staff closed a ticket.",
)
