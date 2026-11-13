"""The emails the shop sends, each under a stable kind name (karni.mail).

* ``shop.shipment_shipped``, to the buyer: the parcel left, with its tracking number.
* ``shop.shipment_delivered``, to the buyer: the parcel arrived.
* ``shop.low_stock``, to the staff (``SHOP_STAFF_EMAILS``): a product runs low.

The order's own emails (confirmation, cancelled, refunded, new order for the staff)
are karni-commerce's. Change a message by putting a template of the same name under
your project's templates, or switch a kind off with ``KARNI_MAIL_DISABLED_KINDS``.
"""

from __future__ import annotations

from typing import Any

from karni.mail import send_templated

from shop import services
from shop.models import Product, Shipment, Variation


def shipment_shipped(shipment: Shipment) -> int:
    return send_templated(
        "shop/email/shipment_shipped",
        to=[shipment.order.email],
        context=services.shipment_context(shipment),
        kind="shop.shipment_shipped",
    )


def shipment_delivered(shipment: Shipment) -> int:
    return send_templated(
        "shop/email/shipment_delivered",
        to=[shipment.order.email],
        context=services.shipment_context(shipment),
        kind="shop.shipment_delivered",
    )


def low_stock(product: Product, variation: Variation | None = None) -> int:
    """A product (or one of its variations) runs low: ``variation`` is the one, or None."""
    context: dict[str, Any] = {
        "product": product,
        "variation": variation,
        "stocked": variation if variation is not None else product,
        "level": product.low_stock_level(),
    }
    return send_templated(
        "shop/email/low_stock",
        to=services.staff_emails(),
        context=context,
        kind="shop.low_stock",
    )
