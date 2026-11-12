"""Closing a ticket: the state change and its event in one transaction."""

from __future__ import annotations

from django.db import transaction

from karni.events import publish
from tests.deskapp.models import Ticket


def close(ticket: Ticket, minutes: int) -> Ticket:
    """Close ``ticket`` and publish ``desk.ticket.closed`` in the same transaction."""
    with transaction.atomic():
        ticket.status = "closed"
        ticket.save(update_fields=["status", "updated_at"])
        publish(
            "desk.ticket.closed",
            subject=ticket,
            person=ticket.requester,
            ticket=str(ticket.pk),
            minutes=minutes,
        )
    return ticket
