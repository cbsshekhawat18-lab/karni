"""Server-side pricing for karni-payments: a checkout must match a booking."""

from decimal import Decimal

from rest_framework.exceptions import ValidationError

from events.models import Booking


def validate_checkout(*, user, amount: Decimal, currency: str, metadata: dict) -> None:
    """KARNI_PAYMENTS_CHECKOUT_VALIDATOR: only a booking's own total can be charged."""
    booking = Booking.objects.filter(pk=metadata.get("booking"), attendee=user).first()
    if booking is None:
        raise ValidationError({"metadata": ["A checkout must name one of your bookings."]})
    if booking.status != Booking.Status.PENDING or Decimal(amount) != booking.total:
        raise ValidationError({"amount": [f"Booking {booking.pk} costs {booking.total}."]})
