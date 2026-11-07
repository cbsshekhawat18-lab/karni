"""bookings models. Each class extends the one karni build writes in
bookings/karni/models.py from karni.yaml: add your methods here.
"""

from typing import Any

from bookings.karni import models as karni
from django.core.exceptions import ValidationError
from django.db import transaction
from karni.capacity import release, reserve
from karni.events import on_deleted, on_restored, on_transition, on_updated
from karni_payments.models import Payment


class Resource(karni.Resource):
    """What is booked. Its price is the price of one booking."""

    def clean(self) -> None:
        if self.price is not None and self.price < 0:
            raise ValidationError({"price": "The price is not negative."})


class Slot(karni.Slot):
    """A time on a resource, for at most ``capacity`` bookings."""

    class APIMeta:
        read_only = ["remaining"]

    def clean(self) -> None:
        if self.capacity is not None and self.capacity < 1:
            raise ValidationError({"capacity": "A slot has room for at least one booking."})
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "A slot ends after it starts."})


class Booking(karni.Booking):
    """A member's place in a slot. A slot takes no more bookings than its capacity."""

    class APIMeta:
        read_only = ["status", "payment"]

    def save(self, *args: Any, **kwargs: Any) -> None:
        with transaction.atomic():  # the place is taken with the row, or neither is
            if self._state.adding and self.status != "cancelled":
                reserve(self.slot)  # a full slot refuses it: 409, E985
            super().save(*args, **kwargs)


@on_transition(Booking, "status", to="cancelled")
def give_the_place_back(booking: Booking) -> None:
    release(booking.slot)


@on_deleted(Booking)
def free_a_deleted_place(booking: Booking) -> None:
    if booking.status != "cancelled":  # a cancelled booking gave its place back already
        release(booking.slot)


@on_restored(Booking)
def take_the_place_again(booking: Booking) -> None:
    if booking.status != "cancelled":
        reserve(booking.slot)


@on_updated(Payment)
def confirm_the_paid_booking(payment: Payment) -> None:
    """The provider settled the payment: its pending booking is confirmed."""
    if payment.status != Payment.Status.SUCCEEDED:
        return
    for booking in Booking.objects.filter(payment=payment, status="pending"):
        booking.transition("status", "confirmed")
