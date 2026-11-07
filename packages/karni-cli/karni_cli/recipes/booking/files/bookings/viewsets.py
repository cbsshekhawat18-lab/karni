"""bookings API. Each viewset extends the one karni build writes in
bookings/karni/api.py from karni.yaml: add your actions here.
"""

from bookings.karni import api as karni
from django.conf import settings
from karni_payments.services import create_checkout
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response


class ResourceViewSet(karni.ResourceViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class SlotViewSet(karni.SlotViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class BookingViewSet(karni.BookingViewSet):
    """A member's bookings: pay for one, or cancel it."""

    @action(detail=True, methods=["post"])
    def pay(self, request: Request, pk: str | None = None) -> Response:
        """Open the payment at the provider. Its webhook confirms the booking."""
        booking = self.get_object()
        back = f"{settings.KARNI_FRONTEND_URL}/bookings/{booking.pk}"
        payment, session = create_checkout(
            request.user,
            amount=booking.slot.resource.price,
            success_url=f"{back}?paid=1",
            cancel_url=back,
            metadata={"booking": str(booking.pk)},
        )
        booking.payment = payment
        booking.save(update_fields=["payment", "updated_at"])
        return Response({"payment": str(payment.pk), "url": session.url})

    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        """Cancel the booking: its place in the slot is free again."""
        booking = self.get_object()
        booking.transition("status", "cancelled")
        return Response(self.get_serializer(booking).data)
