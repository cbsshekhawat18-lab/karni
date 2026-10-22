"""Lifecycle and limited-resource models: one per primitive, plus the PostgreSQL range ones.

``Reservation`` and ``Stay`` use PostgreSQL range columns, which need
psycopg; without it they are not defined (the suite's range tests skip).
"""

from __future__ import annotations

from django.db import models

from karni.constraints import NoOverlap
from karni.fields import CapacityField, StateField
from karni.models import BaseModel

try:
    from karni.fields.ranges import DateRangeField, DateTimeRangeField
except ImportError:  # psycopg is not installed: no range columns
    HAS_RANGES = False
else:
    HAS_RANGES = True


ORDER_STATES = ["draft", "confirmed", "cancelled", "refunded"]
ORDER_TRANSITIONS = {"draft": ["confirmed", "cancelled"], "confirmed": ["cancelled", "refunded"]}


class Order(BaseModel):
    """The README's lifecycle: draft → confirmed → cancelled / refunded."""

    title = models.CharField(max_length=100, blank=True)
    status = StateField(states=ORDER_STATES, transitions=ORDER_TRANSITIONS)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Karni:
        audit = ["title", "status"]

    def __str__(self) -> str:
        return self.title or str(self.pk)


class Ticket(BaseModel):
    """A TextChoices lifecycle with two initial states and no audit trail."""

    class Status(models.TextChoices):
        OPEN = "open"
        TRIAGED = "triaged", "Triaged by support"
        CLOSED = "closed"

    status = StateField(
        states=Status,
        transitions={Status.OPEN: [Status.TRIAGED, Status.CLOSED], Status.TRIAGED: [Status.CLOSED]},
        initial=[Status.OPEN, Status.TRIAGED],
        audit=False,
    )


class Stock(BaseModel):
    """N units exist: ``remaining`` starts at ``quantity`` and never drops below zero."""

    name = models.CharField(max_length=100)
    quantity = models.PositiveIntegerField()
    remaining = CapacityField(total="quantity")

    def __str__(self) -> str:
        return self.name


class Pool(BaseModel):
    """A counter without a ceiling (replenished with release())."""

    name = models.CharField(max_length=100)
    units = CapacityField(default=0)


class Room(BaseModel):
    name = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.name


SLOT_STATES = ["held", "confirmed", "cancelled"]
SLOT_TRANSITIONS = {"held": ["confirmed", "cancelled"], "confirmed": ["cancelled"]}


class Slot(BaseModel):
    """no_overlap over a (start, end) pair: works on any database, enforced on PostgreSQL."""

    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = StateField(states=SLOT_STATES, transitions=SLOT_TRANSITIONS)

    class Karni:
        no_overlap = NoOverlap("room", ("starts_at", "ends_at"), ignore={"status": ["cancelled"]})


if HAS_RANGES:

    class Reservation(BaseModel):
        """no_overlap over a tstzrange; cancelled and soft-deleted rows free the slot."""

        room = models.ForeignKey(Room, on_delete=models.CASCADE)
        during = DateTimeRangeField()
        status = StateField(states=SLOT_STATES, transitions=SLOT_TRANSITIONS)

        class Karni:
            no_overlap = NoOverlap("room", "during", ignore={"status": ["cancelled"]})

    class Stay(BaseModel):
        """The tuple shorthand over a daterange: every live stay blocks its nights."""

        room = models.ForeignKey(Room, on_delete=models.CASCADE)
        nights = DateRangeField()

        class Karni:
            no_overlap = ("room", "nights")
