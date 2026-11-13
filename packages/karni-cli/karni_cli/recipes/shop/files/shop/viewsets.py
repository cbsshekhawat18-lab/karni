"""shop API. Each viewset extends the one karni build writes in shop/karni/api.py from
karni.yaml: add your actions here.

The cart, checkout and orders are karni-commerce's API (/api/carts/current/,
/api/orders/). The shop adds to its products what a shopper needs (the price today,
what is left, every picture, filters by price) and the parcel's moves:

* ``GET products/?min_price=&max_price=&ordering=effective_price``: by the price a
  customer pays now. A shopper sees the active products only. ``?ids=a,b`` reads
  some products by id (the recently viewed ones), and each product carries its
  variations, its options and its price range.
* ``GET products/{id}/related/``: the products to show beside it.
* ``GET reviews/?product=``: the approved reviews of a product (staff read every one,
  a person their own too). ``POST reviews/`` writes one, once the product reached the
  writer. ``GET reviews/eligibility/?product=`` says whether the reader may.
* ``POST shipments/{id}/ship/``: ``{tracking_number, carrier}`` marks the parcel sent.
* ``POST shipments/{id}/deliver/``: marks it delivered.
"""

from __future__ import annotations

from functools import cache
from typing import Any

from django.db.models import Prefetch, QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from karni.api import Budget, Can, Public
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from shop import services
from shop.karni import api as karni
from shop.models import Product, Review, Shipment, Variation
from shop.serializers import (
    EligibilitySerializer,
    OptionSerializer,
    ProductImageSerializer,
    ShipInputSerializer,
    VariationViewSerializer,
    image_url,
)


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
        more_description = serializers.SerializerMethodField()
        gallery = serializers.SerializerMethodField()
        variations = serializers.SerializerMethodField()
        options = serializers.SerializerMethodField()
        price_from = serializers.SerializerMethodField()
        price_to = serializers.SerializerMethodField()
        stock_left = serializers.SerializerMethodField()

        class Meta(base.Meta):  # type: ignore[name-defined]
            fields = [
                *base.Meta.fields,
                "current_price",
                "on_sale",
                "more_description",
                "gallery",
                "variations",
                "options",
                "price_from",
                "price_to",
                "stock_left",
            ]

        def _variations(self, product: Product) -> list[Variation]:
            rows = getattr(product, "shop_active_variations", None)
            if rows is None:
                rows = list(
                    product.variation_set.filter(active=True).prefetch_related(
                        "values__attribute"
                    )
                )
                product.shop_active_variations = rows  # type: ignore[attr-defined]
            return sorted(rows, key=lambda row: (row.position, row.sku))

        @extend_schema_field(VariationViewSerializer(many=True))
        def get_variations(self, product: Product) -> list[dict[str, Any]]:
            return [
                {
                    "id": str(row.pk),
                    "sku": row.sku,
                    "label": row.label(),
                    "values": {
                        value.attribute.name: value.value
                        for value in row.ordered_values()
                    },
                    "price": f"{row.regular_price():.2f}",
                    "current_price": f"{row.current_price():.2f}",
                    "on_sale": row.on_sale(),
                    "available": None if product.backorders else int(row.available),
                    "image": image_url(self.context, row.image),
                }
                for row in self._variations(product)
            ]

        @extend_schema_field(OptionSerializer(many=True))
        def get_options(self, product: Product) -> list[dict[str, Any]]:
            """Each attribute the variations use, with its values in order."""
            found: dict[str, tuple[tuple[int, str], dict[str, int]]] = {}
            for row in self._variations(product):
                for value in row.ordered_values():
                    attribute = value.attribute
                    key = (attribute.position, attribute.name)
                    entry = found.setdefault(attribute.name, (key, {}))
                    entry[1].setdefault(value.value, value.position)
            ordered = sorted(found.items(), key=lambda item: item[1][0])
            return [
                {
                    "name": name,
                    "values": [
                        text
                        for text, _ in sorted(
                            values.items(), key=lambda pair: (pair[1], pair[0])
                        )
                    ],
                }
                for name, (_key, values) in ordered
            ]

        def _prices(self, product: Product) -> list[Any]:
            rows = self._variations(product)
            if not rows:
                return [product.current_price()]
            return [row.current_price() for row in rows]

        def get_price_from(self, product: Product) -> str:
            return f"{min(self._prices(product)):.2f}"

        def get_price_to(self, product: Product) -> str:
            return f"{max(self._prices(product)):.2f}"

        def get_stock_left(self, product: Product) -> int | None:
            """What is left to buy: of the product, or of all its variations."""
            if product.backorders:
                return None
            rows = self._variations(product)
            if rows:
                return sum(int(row.available) for row in rows)
            return int(product.available)

        def get_current_price(self, product: Product) -> str:
            return f"{product.current_price():.2f}"

        def get_on_sale(self, product: Product) -> bool:
            return product.on_sale()

        def get_more_description(self, product: Product) -> str:
            return product.more_description()

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

    prefetch_related = (
        "productimage_set",
        Prefetch(
            "variation_set",
            queryset=Variation.objects.filter(active=True).prefetch_related(
                "values__attribute"
            ),
            to_attr="shop_active_variations",
        ),
    )
    query_budget = Budget(
        list=12,
        retrieve=12,
        update=18,
        partial_update=18,
        related=16,
        reason="a product reads its pictures, its variations with their values and "
        "options (three prefetches), its tags, categories and related products: one "
        "query each, however many products",
    )
    ordering_fields = "__all__"

    def get_serializer_class(self) -> type[Any]:
        return _store_serializer(super().get_serializer_class())

    def get_queryset(self) -> QuerySet[Product]:
        queryset = services.with_effective_price(super().get_queryset())
        user = self.request.user
        if not (user.is_authenticated and user.can("shop.product:change")):
            queryset = queryset.filter(active=True)
        params = self.request.query_params
        ids = [part for part in str(params.get("ids", "") or "").split(",") if part]
        if ids:
            queryset = queryset.filter(pk__in=ids[:50])
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
            OpenApiParameter(
                "ids", str, description="Some products, by id, with commas."
            ),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @action(detail=True, methods=["get"], url_path="related", access=Public())
    def related(self, request: Request, pk: Any = None) -> Response:
        """The products to show beside this one: staff's choice, then its category's."""
        product: Product = self.get_object()
        found = services.related(product)
        rows = (
            self.get_queryset()
            .filter(pk__in=[row.pk for row in found])
            .prefetch_related("tags", "categories", "related")
        )
        order = {row.pk: index for index, row in enumerate(found)}
        ordered = sorted(rows, key=lambda row: order.get(row.pk, 0))
        # karni: allow(unpaginated-action): at most SHOP_RELATED_COUNT rows
        return Response(self.get_serializer(ordered, many=True).data)


class ProductImageViewSet(karni.ProductImageViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class AttributeViewSet(karni.AttributeViewSet):
    """The options products come in (Size, Colour)."""


class AttributeValueViewSet(karni.AttributeValueViewSet):
    """The values of each option (S, M, L)."""

    select_related = ("attribute",)


class VariationViewSet(karni.VariationViewSet):
    """The ways a product is sold, each with its SKU, price and stock."""


@cache
def _review_serializer(
    base: type[serializers.ModelSerializer[Any]], writing: bool
) -> type[Any]:
    """``base`` with the writer's name as a shopper may read it ("Mira O."). For a new
    review (``writing``) the writer, status and verified mark are the server's."""

    class Reviewed(base):  # type: ignore[valid-type,misc]
        author_name = serializers.SerializerMethodField()
        if writing:
            author = serializers.PrimaryKeyRelatedField(read_only=True)
            status = serializers.CharField(read_only=True)
            verified = serializers.BooleanField(read_only=True)

        class Meta(base.Meta):  # type: ignore[name-defined]
            fields = [*base.Meta.fields, "author_name"]

        def get_author_name(self, review: Review) -> str:
            author = review.author
            first = str(getattr(author, "first_name", "") or "").strip()
            last = str(getattr(author, "last_name", "") or "").strip()
            if first:
                return f"{first} {last[:1]}." if last else first
            return "A customer"

    Reviewed.__name__ = base.__name__ + ("Create" if writing else "")
    Reviewed.__qualname__ = Reviewed.__name__
    return Reviewed


class ReviewViewSet(karni.ReviewViewSet):
    """Reviews. A shopper reads the approved ones, staff every one, a writer their own.

    Writing one needs the product to have reached the writer (a delivered parcel of a
    paid order). It waits for staff unless ``SHOP_REVIEWS_NEED_APPROVAL`` is off.
    Staff approve or reject it by its status.
    """

    select_related = ("author", "product")
    filterset_fields = ["product", "status"]

    def get_serializer_class(self) -> type[Any]:
        writing = getattr(self, "action", None) == "create"
        return _review_serializer(super().get_serializer_class(), writing)

    def get_queryset(self) -> QuerySet[Review]:
        queryset: QuerySet[Review] = super().get_queryset()
        user = self.request.user
        if user.is_authenticated and user.can("shop.review:view"):
            return queryset
        from django.db.models import Q

        mine = Q(author=user) if user.is_authenticated else Q(pk__in=[])
        return queryset.filter(Q(status="approved") | mine)

    def perform_create(self, serializer: Any) -> None:
        """A customer reviews what reached them. Staff who moderate reviews may write
        one for any product (a review sent by email): it is marked verified only when
        the product reached them too."""
        user = self.request.user
        product = serializer.validated_data["product"]
        if Review.objects.filter(product=product, author=user).exists():
            raise ValidationError({"product": ["You have reviewed this product."]})
        problem = services.review_problem(user, product)
        if problem and not user.can("shop.review:change"):
            raise ValidationError({"product": [problem]})
        status = "pending" if services.reviews_need_approval() else "approved"
        serializer.save(
            author=user, status=status, verified=services.received(user, product)
        )

    @extend_schema(
        parameters=[OpenApiParameter("product", str, required=True)],
        responses=EligibilitySerializer,
    )
    @action(detail=False, methods=["get"], url_path="eligibility", access=Public())
    def eligibility(self, request: Request) -> Response:
        """Whether the reader may review the product, and their review when they wrote one."""
        found = Product.objects.filter(
            pk=str(request.query_params.get("product", "") or "") or None
        ).first()
        if found is None:
            raise ValidationError({"product": ["No such product."]})
        user = request.user
        mine = (
            Review.objects.filter(product=found, author=user).first()
            if user.is_authenticated
            else None
        )
        problem = services.review_problem(user, found)
        return Response(
            EligibilitySerializer(
                {
                    "can_review": problem == "",
                    "reason": problem,
                    "status": mine.status if mine is not None else None,
                }
            ).data
        )


class WishlistItemViewSet(karni.WishlistItemViewSet):
    """A customer's wishlist: their own rows only. Adding a product twice keeps one."""

    select_related = ("product",)

    def perform_create(self, serializer: Any) -> None:
        from shop.models import WishlistItem

        product = serializer.validated_data["product"]
        found = WishlistItem.objects.filter(
            user=self.request.user, product=product
        ).first()
        if found is not None:
            serializer.instance = found
            return
        super().perform_create(serializer)


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
