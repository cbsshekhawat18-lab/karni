"""shop API. Each viewset extends the one karni build writes in shop/karni/api.py from
karni.yaml: add your actions here.
"""

from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from karni.accounts.permissions import has_role
from karni_payments.services import create_checkout
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from shop.karni import api as karni
from shop.serializers import OrderSerializer


class CategoryViewSet(karni.CategoryViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class ProductViewSet(karni.ProductViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class CartViewSet(karni.CartViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class CartItemViewSet(karni.CartItemViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class OrderViewSet(karni.OrderViewSet):
    """Orders with their items and payment, and the staff's actions on them."""

    serializer_class = OrderSerializer

    def _staff_only(self, request: Request) -> None:
        if isinstance(request.user, AnonymousUser) or not has_role(request.user, "staff"):
            raise PermissionDenied("Only staff may do this.")

    @action(detail=True, methods=["post"])
    def ship(self, request: Request, pk: str | None = None) -> Response:
        self._staff_only(request)
        order = self.get_object()
        if order.status != "paid":
            raise ValidationError({"status": ["Only a paid order can be shipped."]})
        order.transition("status", "shipped")
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["post"])
    def refund(self, request: Request, pk: str | None = None) -> Response:
        self._staff_only(request)
        order = self.get_object()
        if order.status not in ("paid", "shipped"):
            raise ValidationError({"status": ["Only a paid or shipped order can be refunded."]})
        order.refund()
        order.refresh_from_db()
        return Response(self.get_serializer(order).data)


class OrderItemViewSet(karni.OrderItemViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


def open_payment(request: Request, order) -> None:
    """Open the order's payment at the provider."""
    back = f"{settings.KARNI_FRONTEND_URL}/orders/{order.pk}"
    payment, _session = create_checkout(
        request.user,
        amount=Decimal(order.total),
        success_url=f"{back}?paid=1",
        cancel_url=back,
        metadata={"order": str(order.pk)},
    )
    order.payment = payment
    order.save(update_fields=["payment", "updated_at"])
