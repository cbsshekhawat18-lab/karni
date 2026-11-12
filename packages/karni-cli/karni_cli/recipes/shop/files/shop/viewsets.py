"""shop API. Each viewset extends the one karni build writes in shop/karni/api.py from
karni.yaml: add your actions here.

The cart, checkout and orders are karni-commerce's API (/api/carts/current/,
/api/orders/). The shop adds to its products what a shopper needs (the price today,
what is left, every picture, filters by price) and the parcel's moves:

* ``GET products/?min_price=&max_price=&ordering=effective_price``: by the price a
  customer pays now. A shopper sees the active products only.
* ``POST shipments/{id}/ship/``: ``{tracking_number, carrier}`` marks the parcel sent.
* ``POST shipments/{id}/deliver/``: marks it delivered.
"""

from __future__ import annotations

from functools import cache
from typing import Any

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from karni.api import Can
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from shop.karni import api as karni

from shop import services
from shop.models import Product, Shipment
from shop.serializers import ProductImageSerializer, ShipInputSerializer, image_url


class CategoryViewSet(karni.CategoryViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class TagViewSet(karni.TagViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


@cache
def _store_serializer(base: type[serializers.ModelSerializer[Any]]) -> type[Any]:
    """``base`` with what a shopper needs: the price today and every picture."""

    class Store(base):  # type: ignore[valid-type,misc]
        current_price = serializers.SerializerMethodField()
        on_sale = serializers.SerializerMethodField()
        gallery = serializers.SerializerMethodField()

        class Meta(base.Meta):  # type: ignore[name-defined]
            fields = [*base.Meta.fields, "current_price", "on_sale", "gallery"]

        def get_current_price(self, product: Product) -> str:
            return f"{product.current_price():.2f}"

        def get_on_sale(self, product: Product) -> bool:
            return product.on_sale()

        @extend_schema_field(ProductImageSerializer(many=True))
        def get_gallery(self, product: Product) -> list[dict[str, str]]:
            images = sorted(
                product.productimage_set.all(), key=lambda row: row.position
            )
            return [
                {
                    "image": image_url(self.context, row.image) or "",
                    "alt": row.alt or "",
                }
                for row in images
            ]

    Store.__name__ = base.__name__
    Store.__qualname__ = base.__qualname__
    return Store


class ProductViewSet(karni.ProductViewSet):
    """Products. A shopper sees the active ones, with their price today and what is
    left.

    ``?min_price=`` and ``?max_price=`` filter by the price a customer pays now, and
    ``?ordering=effective_price`` sorts by it.
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
                    number = float(value)
                except ValueError:
                    raise ValidationError({name: ["A number."]}) from None
                queryset = queryset.filter(**{f"effective_price__{lookup}": number})
        return queryset

    @extend_schema(
        parameters=[
            OpenApiParameter("min_price", float, description="The lowest price today."),
            OpenApiParameter(
                "max_price", float, description="The highest price today."
            ),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)


class ProductImageViewSet(karni.ProductImageViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class ShipmentViewSet(karni.ShipmentViewSet):
    """Parcels, for staff. ``ship`` and ``deliver`` move one along."""

    select_related = ("order",)

    @extend_schema(request=ShipInputSerializer)
    @action(
        detail=True,
        methods=["post"],
        url_path="ship",
        access=Can("shop.shipment:change"),
    )
    def ship(self, request: Request, pk: Any = None) -> Response:
        """Mark the parcel sent with its tracking number: the buyer gets an email."""
        body = ShipInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        shipment: Shipment = self.get_object()
        services.ship(
            shipment,
            body.validated_data["tracking_number"],
            body.validated_data["carrier"],
        )
        return Response(self.get_serializer(shipment).data)

    @action(
        detail=True,
        methods=["post"],
        url_path="deliver",
        access=Can("shop.shipment:change"),
    )
    def deliver(self, request: Request, pk: Any = None) -> Response:
        """Mark the parcel delivered: the buyer gets an email."""
        shipment: Shipment = self.get_object()
        services.deliver(shipment)
        return Response(self.get_serializer(shipment).data)
