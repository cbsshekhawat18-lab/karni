"""The shop's rules besides the order path: prices today, shipments and stock levels.

The cart, checkout, the payments and refunds are karni-commerce's
(``karni_commerce.services``). The shop decides what a product costs and how its
stock moves (shop/sellables.py) and what happens to the parcel (here).

Settings: ``SHOP_LOW_STOCK`` (3: the level at which ``product_low_stock`` is sent and
staff get an email), ``SHOP_STAFF_EMAILS`` (who gets that email, else
``KARNI_COMMERCE_STAFF_EMAILS``), ``SHOP_REVIEWS_NEED_APPROVAL`` (True: a review
waits for staff before it shows) and ``SHOP_RELATED_COUNT`` (4: the related products
a product page shows).
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import (
    Case,
    DecimalField,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Sum,
    When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone
from karni_commerce.models import Order

from shop.models import Product, Review, Shipment, Variation

#: The money states of an order whose buyer paid for what they got.
PAID = ("paid", "part_paid", "part_refunded")


def low_stock_level() -> int:
    return int(getattr(settings, "SHOP_LOW_STOCK", 3))


def staff_emails() -> list[str]:
    found = getattr(settings, "SHOP_STAFF_EMAILS", None)
    if found is None:
        found = getattr(settings, "KARNI_COMMERCE_STAFF_EMAILS", [])
    return [str(address) for address in found or []]


def with_effective_price(queryset: QuerySet[Product]) -> QuerySet[Product]:
    """Each product with ``effective_price``: what a customer pays now (on sale too)."""
    now = timezone.now()
    on_sale = (
        Q(sale_price__isnull=False)
        & (Q(sale_starts__isnull=True) | Q(sale_starts__lte=now))
        & (Q(sale_ends__isnull=True) | Q(sale_ends__gt=now))
    )
    return queryset.annotate(
        effective_price=Case(
            When(on_sale, then=F("sale_price")),
            default=F("price"),
            output_field=DecimalField(max_digits=19, decimal_places=4),
        )
    )


def with_stock(queryset: QuerySet[Product]) -> QuerySet[Product]:
    """Each product with its stock as a shopper and staff read it.

    ``stock_total`` and ``available_total`` are the product's own ``stock`` and
    ``available``, or for a product with active variations the sum of theirs: such a
    product is bought by its variations, so its own figures do not move.
    ``has_variations`` says which. The product list, its filters, the home tiles and
    the API all read these, so "Sold out" and "Running low" follow the variations.
    """
    active = Variation.objects.filter(product=OuterRef("pk"), active=True)

    def total(field: str) -> Coalesce:
        summed = (
            active.order_by()
            .values("product")
            .annotate(total=Sum(field))
            .values("total")[:1]
        )
        return Coalesce(
            Subquery(summed, output_field=IntegerField()),
            F(field),
            output_field=IntegerField(),
        )

    return queryset.annotate(
        has_variations=Exists(active),
        stock_total=total("stock"),
        available_total=total("available"),
    )


def ships(order: Order) -> bool:
    """Whether the order has products to send (a shipment of its own)."""
    return order.lines.filter(kind="product", needs_shipping=True).exists()


@transaction.atomic
def open_shipment(order: Order) -> Shipment | None:
    """The paid order's parcel, waiting to be sent (one per order)."""
    if not ships(order):
        return None
    found = Shipment.objects.filter(order=order).first()
    return found or Shipment.objects.create(order=order, status="processing")


@transaction.atomic
def ship(shipment: Shipment, tracking_number: str, carrier: str = "") -> Shipment:
    """Mark the parcel sent, with its tracking number (the buyer gets an email)."""
    shipment.transition(
        "status", "shipped", tracking_number=tracking_number, carrier=carrier
    )
    return shipment


@transaction.atomic
def deliver(shipment: Shipment) -> Shipment:
    """Mark the parcel delivered (the buyer gets an email)."""
    shipment.transition("status", "delivered")
    return shipment


def cancel_shipment(order: Order) -> None:
    """The order was cancelled: a parcel not sent yet will not be."""
    for shipment in Shipment.objects.filter(order=order, status="processing"):
        shipment.transition("status", "cancelled")


def shipment_context(shipment: Any) -> dict[str, Any]:
    from karni_commerce.services import order_link

    order = shipment.order
    return {
        "shipment": shipment,
        "order": order,
        "lines": list(order.lines.filter(kind="product")),
        "link": order_link(order),
    }


def reviews_need_approval() -> bool:
    return bool(getattr(settings, "SHOP_REVIEWS_NEED_APPROVAL", True))


def related_count() -> int:
    return int(getattr(settings, "SHOP_RELATED_COUNT", 4))


def received(user: Any, product: Product) -> bool:
    """Whether ``user`` paid for ``product`` (any variation) and its parcel arrived."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    orders = Order.objects.filter(
        user=user,
        status__in=PAID,
        lines__kind="product",
        lines__item=str(product.pk),
    )
    return Shipment.objects.filter(order__in=orders, status="delivered").exists()


def review_problem(user: Any, product: Product) -> str:
    """Why ``user`` may not review ``product``, in words, or "" when they may."""
    if user is None or not getattr(user, "is_authenticated", False):
        return "Sign in to review a product you bought."
    if Review.objects.filter(product=product, author=user).exists():
        return "You have reviewed this product."
    if not received(user, product):
        return "You can review a product once it has reached you."
    return ""


def related(product: Product, count: int | None = None) -> list[Product]:
    """The products to show beside ``product``: staff's choice, then its category's.

    Active products only, never the product itself. Staff's choices come first in
    their order, and the rest are the same categories' best rated and featured.
    """
    wanted = related_count() if count is None else count
    chosen = list(
        product.related.filter(active=True).exclude(pk=product.pk).order_by("name")
    )[:wanted]
    if len(chosen) < wanted:
        more = (
            Product.objects.filter(active=True, categories__in=product.categories.all())
            .exclude(pk__in=[product.pk, *[row.pk for row in chosen]])
            .order_by("-featured", "-rating_average", "name")
            .distinct()
        )
        chosen += list(more[: wanted - len(chosen)])
    return chosen
