"""The emails the shop sends, each under a stable kind name (karni.mail).

* ``shop.shipment_shipped``, to the buyer: the parcel left, with its tracking number.
* ``shop.shipment_delivered``, to the buyer: the parcel arrived.
* ``shop.downloads_ready``, to the buyer: the links to the files of a digital product.
* ``shop.low_stock``, to the staff: a product runs low.

The order's own emails (confirmation, cancelled, refunded, new order for the staff)
are karni-commerce's. A shop manager rewrites any of them on the Settings page
(Emails), with the merge fields declared here, and switches one off there. The
files under shop/templates/shop/email/ are where an edit starts from.
"""

from __future__ import annotations

from typing import Any

from karni.mail import register_kind, send_templated
from karni_commerce.messages import business

from shop import services
from shop.models import Download, Product, Shipment, Variation

#: What every order email of the shop may use.
ORDER_FIELDS = {
    "business.name": "The business's name (Settings, Details)",
    "order.number": "The order's number",
    "order.buyer_name": "The buyer's name (may be blank)",
    "order.email": "The buyer's email",
    "link": "The order's page",
}

register_kind(
    "shop.shipment_shipped",
    title="Parcel shipped",
    template="shop/email/shipment_shipped",
    audience="the buyer",
    describe="The parcel left, with the carrier and the tracking number.",
    fields={
        **ORDER_FIELDS,
        "shipment.carrier": "The carrier (may be blank)",
        "shipment.tracking_number": "The tracking number",
        "lines.quantity": "Each line's quantity",
        "lines.name": "Each line's name",
    },
)
register_kind(
    "shop.shipment_delivered",
    title="Parcel delivered",
    template="shop/email/shipment_delivered",
    audience="the buyer",
    describe="The parcel arrived.",
    fields=ORDER_FIELDS,
)
register_kind(
    "shop.downloads_ready",
    title="Your downloads",
    template="shop/email/downloads_ready",
    audience="the buyer",
    describe="The links to the files of the digital products they paid for.",
    fields={
        **ORDER_FIELDS,
        "downloads.name": "Each file's name",
        "downloads.product": "The product it belongs to",
        "downloads.link": "The link that downloads it",
        "downloads.limit": "How often it may be downloaded",
        "downloads.expires_at": "Until when the link works (may be blank)",
    },
)
register_kind(
    "shop.low_stock",
    title="Low stock",
    template="shop/email/low_stock",
    audience="the staff",
    describe="An order left a product (or one of its variations) at its low-stock level.",
    fields={
        "business.name": "The business's name",
        "name": "The product, or the variation, in words",
        "stocked.sku": "Its SKU",
        "stocked.available": "How many are left to sell",
        "stocked.stock": "How many are on the shelf",
        "level": "The low-stock level",
    },
)


def _shipment(shipment: Shipment) -> dict[str, Any]:
    return {**services.shipment_context(shipment), "business": business()}


def shipment_shipped(shipment: Shipment) -> int:
    return send_templated(
        "shop/email/shipment_shipped",
        to=[shipment.order.email],
        context=_shipment(shipment),
        kind="shop.shipment_shipped",
    )


def shipment_delivered(shipment: Shipment) -> int:
    return send_templated(
        "shop/email/shipment_delivered",
        to=[shipment.order.email],
        context=_shipment(shipment),
        kind="shop.shipment_delivered",
    )


def downloads_ready(order: Any) -> int:
    """The buyer's links to the files they paid for."""
    from karni_commerce.services import order_link

    rows = Download.objects.filter(order=order).select_related("file", "product")
    downloads = [
        {
            "name": row.file.name,
            "product": row.product.name,
            "link": services.download_link(row),
            "limit": row.limit,
            "expires_at": row.expires_at,
        }
        for row in rows
    ]
    return send_templated(
        "shop/email/downloads_ready",
        to=[order.email],
        context={
            "business": business(),
            "order": order,
            "downloads": downloads,
            "link": order_link(order),
        },
        kind="shop.downloads_ready",
    )


def low_stock(product: Product, variation: Variation | None = None) -> int:
    """A product, or its ``variation`` when one is given, runs low."""
    context: dict[str, Any] = {
        "business": business(),
        "product": product,
        "variation": variation,
        "stocked": variation if variation is not None else product,
        "name": str(variation if variation is not None else product),
        "level": product.low_stock_level(),
    }
    return send_templated(
        "shop/email/low_stock",
        to=services.staff_emails(),
        context=context,
        kind="shop.low_stock",
    )
