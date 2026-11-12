"""shop API. Each viewset extends the one karni build writes in shop/karni/api.py from
karni.yaml: add your actions here.

The storefront's endpoints (open to visitors, each checked below):

* ``GET carts/current/``: the cart of the signed-in customer, or the visitor's cart its
  ``X-Cart-Token`` header names.
* ``POST carts/current/items/``: ``{product, quantity}`` puts that many in the cart (0 takes
  it out). A visitor's first item starts their cart, and the answer carries its token.
* ``POST carts/current/merge/``: after sign-in, ``{token}`` joins the visitor's cart to the
  customer's.
* ``POST carts/current/checkout/``: the cart becomes an order waiting for its payment, and
  the answer says where to pay.
* ``GET orders/lookup/?number=&key=``: one order, for its customer or the guest with its key.
* ``POST orders/pay/``: ``{number, key}`` starts the payment of an order that waits for it.
"""

from __future__ import annotations

from functools import cache
from typing import Any

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from karni.api import Authenticated, Budget, Public
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from shop.karni import api as karni

from shop import services
from shop.models import Address, Order, Product
from shop.serializers import (
    CartSerializer,
    CheckoutResultSerializer,
    CheckoutSerializer,
    MergeSerializer,
    OrderViewSerializer,
    PayResultSerializer,
    SetQuantitySerializer,
    image_url,
)

TOKEN_HEADER = "X-Cart-Token"


class CategoryViewSet(karni.CategoryViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class TagViewSet(karni.TagViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class _ProductImageSerializer(serializers.Serializer[Any]):
    image = serializers.CharField()
    alt = serializers.CharField()


@cache
def _store_serializer(base: type[serializers.ModelSerializer[Any]]) -> type[Any]:
    """``base`` with what a shopper needs: the price today, what is left and every picture."""

    class Store(base):  # type: ignore[valid-type,misc]
        current_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
        on_sale = serializers.BooleanField(read_only=True)
        available = serializers.IntegerField(read_only=True)
        gallery = serializers.SerializerMethodField()

        class Meta(base.Meta):  # type: ignore[name-defined]
            fields = [*base.Meta.fields, "current_price", "on_sale", "available", "gallery"]

        @extend_schema_field(_ProductImageSerializer(many=True))
        def get_gallery(self, product: Product) -> list[dict[str, str]]:
            images = sorted(product.productimage_set.all(), key=lambda row: row.position)
            return [
                {"image": image_url(self.context, row.image) or "", "alt": row.alt or ""}
                for row in images
            ]

    Store.__name__ = base.__name__
    Store.__qualname__ = base.__qualname__
    return Store


class ProductViewSet(karni.ProductViewSet):
    """Products. A shopper sees the active ones, with their price today and what is left.

    ``?min_price=`` and ``?max_price=`` filter by the price a customer pays now,
    and ``?ordering=effective_price`` sorts by it.
    """

    prefetch_related = ("productimage_set",)
    ordering_fields = "__all__"

    def get_serializer_class(self) -> type[Any]:
        return _store_serializer(super().get_serializer_class())

    def get_queryset(self) -> QuerySet[Product]:
        queryset = services.with_effective_price(super().get_queryset())
        user = self.request.user
        if not (user.is_authenticated and user.can("shop.product:change")):
            queryset = queryset.filter(active=True)
        params = self.request.query_params
        for name, lookup in (("min_price", "gte"), ("max_price", "lte")):
            value = params.get(name)
            if value:
                try:
                    queryset = queryset.filter(**{f"effective_price__{lookup}": float(value)})
                except ValueError:
                    raise ValidationError({name: ["A number."]}) from None
        return queryset

    @extend_schema(
        parameters=[
            OpenApiParameter("min_price", float, description="The lowest price today."),
            OpenApiParameter("max_price", float, description="The highest price today."),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)


class ProductImageViewSet(karni.ProductImageViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class CartViewSet(karni.CartViewSet):
    """Carts. Staff read them all, and every shopper works on their own through ``current``."""

    query_budget = Budget(
        checkout=60,
        merge=40,
        reason="checkout writes the order, its lines, each line's stock and the payment, and "
        "merging moves each line: a few queries per line, measured with 10 lines",
    )

    def _current(self, request: Request, *, create: bool = False) -> Any:
        return services.find_cart(request.user, request.headers.get(TOKEN_HEADER), create=create)

    def _cart(self, request: Request, cart: Any, status: int = 200) -> Response:
        return Response(CartSerializer.of(cart, context={"request": request}), status=status)

    @extend_schema(responses=CartSerializer)
    @action(detail=False, methods=["get"], url_path="current", access=Public())
    def current(self, request: Request) -> Response:
        """The shopper's cart (empty when they have none yet)."""
        return self._cart(request, self._current(request))

    @extend_schema(request=SetQuantitySerializer, responses=CartSerializer)
    @action(detail=False, methods=["post"], url_path="current/items", access=Public())
    def set_item(self, request: Request) -> Response:
        """Put ``quantity`` of ``product`` in the cart: 0 takes it out."""
        body = SetQuantitySerializer(data=request.data)
        body.is_valid(raise_exception=True)
        cart = self._current(request, create=True)
        services.set_quantity(cart, body.validated_data["product"], body.validated_data["quantity"])
        return self._cart(request, cart)

    @extend_schema(request=MergeSerializer, responses=CartSerializer)
    @action(detail=False, methods=["post"], url_path="current/merge", access=Authenticated())
    def merge(self, request: Request) -> Response:
        """The visitor's cart (by its token) joins the signed-in customer's cart."""
        body = MergeSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return self._cart(request, services.merge(request.user, body.validated_data["token"]))

    @extend_schema(request=CheckoutSerializer, responses={201: CheckoutResultSerializer})
    @action(detail=False, methods=["post"], url_path="current/checkout", access=Public())
    def checkout(self, request: Request) -> Response:
        """The cart becomes an order, its stock is held, and its payment starts."""
        body = CheckoutSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        user = request.user if request.user.is_authenticated else None
        email = (user.email if user is not None else "") or data["email"]
        if not email:
            raise ValidationError({"email": ["An email address, for the confirmation."]})
        cart = self._current(request)
        if cart is None:
            raise ValidationError({"cart": ["The cart is empty."]})
        billing = dict(data["billing"])
        shipping = dict(data["shipping"] or billing)
        order = services.place_order(
            cart, customer=user, email=email, billing=billing, shipping=shipping, note=data["note"]
        )
        if user is not None and data["save_address"]:
            Address.objects.get_or_create(
                customer=user,
                line1=shipping["line1"],
                postcode=shipping["postcode"],
                defaults={
                    **{k: v for k, v in shipping.items() if k not in ("line1", "postcode")},
                    "is_default": not Address.objects.filter(customer=user).exists(),
                },
            )
        url = services.open_payment(order)
        result = {"number": order.number, "key": order.key, "url": url}
        return Response(CheckoutResultSerializer(result).data, status=201)


class CartItemViewSet(karni.CartItemViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class AddressViewSet(karni.AddressViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class _OrderKeySerializer(serializers.Serializer[Any]):
    number = serializers.IntegerField()
    key = serializers.CharField(required=False, allow_blank=True, default="")


class OrderViewSet(karni.OrderViewSet):
    """Orders. A customer reads their own, and a guest the one whose key they hold."""

    def _find(self, request: Request, number: Any, key: str) -> Order:
        order = Order.objects.filter(number=number).first()
        user = request.user
        mine = order is not None and user.is_authenticated and order.customer_id == user.pk
        staff = user.is_authenticated and user.can("shop.order:change")
        if order is None or not (mine or staff or (key and key == order.key)):
            raise NotFound("No such order.")
        return order

    @extend_schema(
        parameters=[
            OpenApiParameter("number", int, required=True),
            OpenApiParameter("key", str, description="The guest's key, from checkout."),
        ],
        responses=OrderViewSerializer,
    )
    @action(detail=False, methods=["get"], url_path="lookup", access=Public())
    def lookup(self, request: Request) -> Response:
        """One order with its lines and addresses, for its customer or the guest with its key."""
        body = _OrderKeySerializer(data=request.query_params)
        body.is_valid(raise_exception=True)
        order = self._find(request, body.validated_data["number"], body.validated_data["key"])
        return Response(OrderViewSerializer(order, context={"request": request}).data)

    @extend_schema(request=_OrderKeySerializer, responses=PayResultSerializer)
    @action(detail=False, methods=["post"], url_path="pay", access=Public())
    def pay(self, request: Request) -> Response:
        """Start the payment again for an order that still waits for it."""
        body = _OrderKeySerializer(data=request.data)
        body.is_valid(raise_exception=True)
        order = self._find(request, body.validated_data["number"], body.validated_data["key"])
        return Response(PayResultSerializer({"url": services.open_payment(order)}).data)


class OrderItemViewSet(karni.OrderItemViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""
