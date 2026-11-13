"""The shop's reactions: a paid order gets a parcel, and a parcel's moves send mail.

Karni imports this module at startup (``karni.events`` autodiscovery).
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.dispatch import receiver
from karni.events import on_transition
from karni_commerce.events import order_cancelled, order_paid
from karni_commerce.models import Order

from shop import events, messages, services
from shop.models import Product, Shipment, Variation


@receiver(order_paid)
def prepare_the_parcel(sender: Any, order: Order, **kwargs: Any) -> None:
    """A paid order with products waits to be sent."""
    services.open_shipment(order)


@receiver(order_paid)
def hand_over_the_files(sender: Any, order: Order, **kwargs: Any) -> None:
    """A paid order's digital products: their downloads, and the email of links."""
    if services.grant_downloads(order):
        pk = order.pk

        def send() -> None:
            found = Order.objects.filter(pk=pk).first()
            if found is not None:
                messages.downloads_ready(found)

        transaction.on_commit(send)


@receiver(order_cancelled)
def stop_the_parcel(sender: Any, order: Order, **kwargs: Any) -> None:
    """A cancelled order's parcel is not sent."""
    services.cancel_shipment(order)


@on_transition(Shipment, "status", to="shipped")
def tell_the_buyer_it_left(shipment: Shipment) -> None:
    events.shipment_shipped.send(sender=Shipment, shipment=shipment)
    pk = shipment.pk
    transaction.on_commit(lambda: _send(pk, messages.shipment_shipped))


@on_transition(Shipment, "status", to="delivered")
def tell_the_buyer_it_arrived(shipment: Shipment) -> None:
    events.shipment_delivered.send(sender=Shipment, shipment=shipment)
    pk = shipment.pk
    transaction.on_commit(lambda: _send(pk, messages.shipment_delivered))


@receiver(events.product_low_stock)
def tell_the_staff_it_runs_low(
    sender: Any, product: Product, variation: Variation | None = None, **kwargs: Any
) -> None:
    pk = product.pk
    variation_pk = variation.pk if variation is not None else None

    def send() -> None:
        found = Product.objects.filter(pk=pk).first()
        which = (
            Variation.objects.filter(pk=variation_pk).first() if variation_pk else None
        )
        if found is not None:
            messages.low_stock(found, which)

    transaction.on_commit(send)


def _send(pk: Any, send: Any) -> None:
    shipment = Shipment.objects.select_related("order").filter(pk=pk).first()
    if shipment is not None:
        send(shipment)
