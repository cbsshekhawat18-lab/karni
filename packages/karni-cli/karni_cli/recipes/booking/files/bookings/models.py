"""bookings models. Each class extends the one karni build writes in
bookings/karni/models.py from karni.yaml: add your methods here.
"""

from typing import Any

from bookings.karni import models as karni
from django.core.exceptions import ValidationError
from django.db import transaction
from karni import preferences
from karni.capacity import release, reserve
from karni.events import on_deleted, on_restored, on_transition, on_updated, publish
from karni_payments.models import Payment


class Resource(karni.Resource):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class Slot(karni.Slot):
    """A time on a resource, for at most ``capacity`` bookings."""

    def clean(self) -> None:
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
    """The provider's webhook settled the payment: its pending booking is confirmed."""
    if payment.status != Payment.Status.SUCCEEDED:
        return
    for booking in Booking.objects.filter(payment=payment, status="pending"):
        booking.transition("status", "confirmed")


@on_transition(Booking, "status", to="confirmed")
def announce_a_confirmed_booking(booking: Booking) -> None:
    _announce(booking, "confirmed")


@on_transition(Booking, "status", to="cancelled")
def announce_a_cancelled_booking(booking: Booking) -> None:
    _announce(booking, "cancelled")


def _announce(booking: Booking, moment: str) -> None:
    """Publish the move as a family event while bookings.family_events is on."""
    if not preferences.active("bookings.family_events"):
        return
    publish(
        f"bookings.booking.{moment}",
        subject=booking,
        booking=str(booking.pk),
        slot=str(booking.slot_id),
        starts_at=booking.slot.starts_at.isoformat(),
    )
