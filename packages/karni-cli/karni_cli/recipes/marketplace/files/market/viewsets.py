"""market API. Each viewset extends the one karni build writes in market/karni/api.py
from karni.yaml: add your actions here.
"""

from django.conf import settings
from karni_payments.services import create_checkout
from market.karni import api as karni
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response


class SellerViewSet(karni.SellerViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class ListingViewSet(karni.ListingViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class OrderViewSet(karni.OrderViewSet):
    """Orders, and paying for one."""

    @action(detail=True, methods=["post"])
    def pay(self, request: Request, pk: str | None = None) -> Response:
        """Open the payment at the provider. Its webhook marks the order paid."""
        order = self.get_object()
        back = f"{settings.KARNI_FRONTEND_URL}/orders/{order.pk}"
        payment, session = create_checkout(
            request.user,
            amount=order.amount,
            success_url=f"{back}?paid=1",
            cancel_url=back,
            metadata={"order": str(order.pk)},
        )
        order.payment = payment
        order.save(update_fields=["payment", "updated_at"])
        return Response({"payment": str(payment.pk), "url": session.url})


class PayoutViewSet(karni.PayoutViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""
