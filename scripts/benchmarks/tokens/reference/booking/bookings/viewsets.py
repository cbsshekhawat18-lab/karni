"""bookings API. Each viewset extends the one karni build writes in
bookings/karni/api.py from karni.yaml: add your actions here.
"""

from bookings.karni import api as karni
from django.conf import settings
from karni_payments.services import create_checkout
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from bookings.serializers import PaymentSerializer


class ResourceViewSet(karni.ResourceViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class SlotViewSet(karni.SlotViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class BookingViewSet(karni.BookingViewSet):
    """A member's bookings: pay for one, or cancel it."""

    @action(detail=True, methods=["post"])
    def pay(self, request: Request, pk: str | None = None) -> Response:
        """Open the payment at the provider. Confirming it confirms the booking."""
        booking = self.get_object()
        if booking.member_id != request.user.pk:
            raise ValidationError("Only the member pays for a booking.")
        if booking.status != "pending" or booking.payment_id:
            raise ValidationError("This booking cannot be paid.")
        back = f"{settings.KARNI_FRONTEND_URL}/bookings/{booking.pk}"
        payment, _session = create_checkout(
            request.user,
            amount=booking.slot.resource.price,
            success_url=f"{back}?paid=1",
            cancel_url=back,
            metadata={"booking": str(booking.pk)},
        )
        booking.payment = payment
        booking.save(update_fields=["payment", "updated_at"])
        return Response(PaymentSerializer(payment).data, status=201)

    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        """Cancel the booking: its place in the slot is free again."""
        booking = self.get_object()
        if booking.status == "cancelled":
            raise ValidationError("This booking is already cancelled.")
        booking.transition("status", "cancelled")
        return Response(self.get_serializer(booking).data)
