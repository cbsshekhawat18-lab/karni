"""bookings API. Each viewset extends the one karni build writes in
bookings/karni/api.py from karni.yaml: add your actions here.

karni.yaml declares the row actions (pay, cancel, confirm) with the states and
roles where each is legal: Karni refuses them elsewhere (409, E997) and routes
confirm itself. pay and cancel do more than move the state, so they are here.
"""

from typing import Any

from bookings.karni import api as karni
from django.conf import settings
from django.db import transaction
from karni.api.actions import RowActionRefused
from karni_payments.models import Payment
from karni_payments.services import create_checkout, create_refund
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

#: A payment still waiting for the customer: pay again sends them back to it.
OPEN = (Payment.Status.PENDING, Payment.Status.PROCESSING)


class ResourceViewSet(karni.ResourceViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class SlotViewSet(karni.SlotViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class BookingViewSet(karni.BookingViewSet):
    """A member's bookings: pay for one, or cancel it (a paid one is refunded)."""

    @action(detail=True, methods=["post"])
    def pay(self, request: Request, pk: str | None = None) -> Response:
        """Open the payment at the provider. Its webhook confirms the booking.

        Calling it again while the payment is open returns the same payment
        and checkout page, so a double click never charges twice.
        """
        booking = self.get_object()
        payment = booking.payment
        if payment is not None and payment.status == Payment.Status.SUCCEEDED:
            raise RowActionRefused(
                f"Booking {booking.pk} is paid already: it is confirmed when the "
                "provider's webhook arrives.",
                field="payment",
                details={"action": "pay", "payment": str(payment.pk)},
            )
        if (
            payment is not None
            and payment.status in OPEN
            and payment.metadata.get("url")
        ):
            return Response(
                {"payment": str(payment.pk), "url": payment.metadata["url"]}
            )
        back = f"{settings.KARNI_FRONTEND_URL}/bookings/{booking.pk}"
        payment, session = create_checkout(
            request.user,
            amount=booking.slot.resource.price,
            success_url=f"{back}?paid=1",
            cancel_url=back,
            metadata={"booking": str(booking.pk)},
        )
        payment.metadata = {**payment.metadata, "url": session.url}
        payment.save(update_fields=["metadata", "updated_at"])
        booking.payment = payment
        booking.save(update_fields=["payment", "updated_at"])
        return Response({"payment": str(payment.pk), "url": session.url})

    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        """Cancel the booking: its place is free again, a paid one is refunded."""
        booking = self.get_object()
        refund = None
        with transaction.atomic():
            booking.transition("status", "cancelled")
            payment = booking.payment
            if payment is not None and payment.status == Payment.Status.SUCCEEDED:
                refund = create_refund(payment, reason="booking cancelled")
        data: dict[str, Any] = dict(self.get_serializer(booking).data)
        data["refund"] = (
            None
            if refund is None
            else {
                "id": str(refund.pk),
                "amount": str(refund.amount),
                "status": refund.status,
            }
        )
        return Response(data)
