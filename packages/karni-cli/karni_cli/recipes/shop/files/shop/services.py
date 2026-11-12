"""The shop's rules besides the order path: prices today, shipments and stock levels.

The cart, checkout, the payments and refunds are karni-commerce's
(``karni_commerce.services``). The shop decides what a product costs and how its
stock moves (shop/sellables.py) and what happens to the parcel (here).

Settings: ``SHOP_LOW_STOCK`` (3: the level at which ``product_low_stock`` is sent and
staff get an email) and ``SHOP_STAFF_EMAILS`` (who gets that email, else
``KARNI_COMMERCE_STAFF_EMAILS``).
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Case, DecimalField, F, Q, QuerySet, When
from django.utils import timezone
from karni_commerce.models import Order

from shop.models import Product, Shipment


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
