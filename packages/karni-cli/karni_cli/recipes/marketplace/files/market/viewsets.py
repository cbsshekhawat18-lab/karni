"""market API. Each viewset extends the one karni build writes in market/karni/api.py
from karni.yaml: add your actions here.

karni.yaml declares the order's row actions (pay, cancel, ship, deliver,
refund) and the payout's mark_paid with the states and roles where each is
legal: Karni refuses them elsewhere (409, E997) and routes the ones that only
move the state. pay and refund do more, so they are here.
"""

from typing import Any

from django.conf import settings
from django.db import transaction
from karni.api.actions import RowActionRefused
from karni_payments.models import Payment
from karni_payments.services import create_checkout, create_refund
from market.karni import api as karni
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from market.models import Payout

#: A payment still waiting for the buyer: pay again sends them back to it.
OPEN = (Payment.Status.PENDING, Payment.Status.PROCESSING)


class SellerViewSet(karni.SellerViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class ListingViewSet(karni.ListingViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class OrderViewSet(karni.OrderViewSet):
    """Orders: pay for one, and staff refund a paid one (its payout is voided)."""

    @action(detail=True, methods=["post"])
    def pay(self, request: Request, pk: str | None = None) -> Response:
        """Open the payment at the provider. Its webhook marks the order paid.

        Calling it again while the payment is open returns the same payment
        and checkout page, so a double click never charges twice.
        """
        order = self.get_object()
        payment = order.payment
        if payment is not None and payment.status == Payment.Status.SUCCEEDED:
            raise RowActionRefused(
                f"Order {order.pk} is paid already: it is marked paid when the "
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
        back = f"{settings.KARNI_FRONTEND_URL}/orders/{order.pk}"
        payment, session = create_checkout(
            request.user,
            amount=order.amount,
            success_url=f"{back}?paid=1",
            cancel_url=back,
            metadata={"order": str(order.pk)},
        )
        payment.metadata = {**payment.metadata, "url": session.url}
        payment.save(update_fields=["metadata", "updated_at"])
        order.payment = payment
        order.save(update_fields=["payment", "updated_at"])
        return Response({"payment": str(payment.pk), "url": session.url})

    @action(detail=True, methods=["post"])
    def refund(self, request: Request, pk: str | None = None) -> Response:
        """Refund a paid order in full: its payout is void, its payment refunded."""
        order = self.get_object()
        refund = None
        with transaction.atomic():
            order.transition("status", "refunded")
            payout = Payout.objects.filter(order=order).first()
            if payout is not None and payout.status == "pending":
                payout.transition("status", "void")
            payment = order.payment
            if payment is not None and payment.status == Payment.Status.SUCCEEDED:
                refund = create_refund(payment, reason="order refunded")
        data: dict[str, Any] = dict(self.get_serializer(order).data)
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


class PayoutViewSet(karni.PayoutViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""
