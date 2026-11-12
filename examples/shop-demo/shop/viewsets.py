"""shop API. Each viewset extends the one karni build writes in shop/karni/api.py from
karni.yaml: add your actions here.
"""

from django.conf import settings
from karni_payments.services import create_checkout
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from shop.karni import api as karni


class CategoryViewSet(karni.CategoryViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class ProductViewSet(karni.ProductViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class CartViewSet(karni.CartViewSet):
    """The customer's carts, and checkout."""

    @action(detail=True, methods=["post"])
    def checkout(self, request: Request, pk: str | None = None) -> Response:
        """The cart becomes an order, and its payment opens at the provider."""
        order = self.get_object().checkout()
        back = f"{settings.KARNI_FRONTEND_URL}/orders/{order.pk}"
        payment, session = create_checkout(
            request.user,
            amount=order.total,
            success_url=f"{back}?paid=1",
            cancel_url=back,
            metadata={"order": str(order.pk)},
        )
        order.payment = payment
        order.save(update_fields=["payment", "updated_at"])
        body = {"order": str(order.pk), "payment": str(payment.pk), "url": session.url}
        return Response(body, status=201)


class CartItemViewSet(karni.CartItemViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class OrderViewSet(karni.OrderViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class OrderItemViewSet(karni.OrderItemViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""
