"""The help desk's services: open and close a ticket, publishing the family events."""

from __future__ import annotations

from typing import Any

from django.db import transaction

from karni.events import publish
from tests.helpdeskapp.models import Ticket


def open_ticket(person: Any, topic: str) -> Ticket:
    """Open a ticket for ``person`` and publish ``helpdeskapp.ticket.opened``."""
    with transaction.atomic():
        ticket = Ticket.objects.create(person=person, subject=topic)
        publish(
            "helpdeskapp.ticket.opened",
            subject=ticket,
            person=person,
            ticket=str(ticket.pk),
            topic=topic,
        )
    return ticket


def close_ticket(ticket: Ticket, minutes: int) -> Ticket:
    """Close ``ticket`` and publish ``helpdeskapp.ticket.closed``."""
    with transaction.atomic():
        ticket.status = "closed"
        ticket.save(update_fields=["status", "updated_at"])
        publish(
            "helpdeskapp.ticket.closed",
            subject=ticket,
            person=ticket.person_id,
            ticket=str(ticket.pk),
            topic=ticket.subject,
            minutes=minutes,
        )
    return ticket
