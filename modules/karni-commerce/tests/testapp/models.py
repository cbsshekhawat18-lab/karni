"""Things to sell that are not a shop's products: a gadget, a workshop seat and a slot.

The slot is a dry run of the booking recipe's bookable: a time with seats, a
deposit and a short hold, booked tentatively at checkout and confirmed when paid.
"""

from __future__ import annotations

from django.db import models
from karni.fields import CapacityField, MoneyField
from karni.models import BaseModel


class Gadget(BaseModel):
    """A thing on a shelf: stock that checkout holds, sent to an address."""

    name = models.CharField(max_length=100)
    sku = models.CharField(max_length=20, blank=True, default="")
    price = MoneyField(currency="EUR")
    sale_price = MoneyField(currency="EUR", null=True, blank=True)
    stock = models.PositiveIntegerField(default=0)
    available = CapacityField(total="stock")

    def __str__(self) -> str:
        return self.name


class Workshop(BaseModel):
    """A seat in a workshop on a day: seats that checkout holds, nothing to ship."""

    title = models.CharField(max_length=100)
    price = MoneyField(currency="EUR")
    seats = models.PositiveIntegerField(default=10)
    free_seats = CapacityField(total="seats")
    starts_at = models.DateTimeField()
    enrolled = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return self.title


class Slot(BaseModel):
    """A time that can be booked: seats held at checkout for a few minutes, a deposit."""

    title = models.CharField(max_length=100)
    starts_at = models.DateTimeField()
    price = MoneyField(currency="EUR")
    deposit = MoneyField(currency="EUR", default=0)
    seats = models.PositiveIntegerField(default=1)
    free_seats = CapacityField(total="seats")

    def __str__(self) -> str:
        return self.title


class Booking(BaseModel):
    """A booking of a slot by an order line: held at checkout, confirmed once paid.

    It names the order line by its id as text: the booking part never points a
    foreign key at commerce's rows it does not own, and commerce never knows bookings.
    """

    class Status(models.TextChoices):
        HELD = "held"
        CONFIRMED = "confirmed"
        RELEASED = "released"
        CANCELLED = "cancelled"

    slot = models.ForeignKey(Slot, on_delete=models.PROTECT, related_name="bookings")
    order_line = models.CharField(max_length=64)
    seats = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.HELD)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["order_line"], name="testapp_booking_one_per_line")
        ]

    def __str__(self) -> str:
        return f"{self.slot} ({self.status})"
