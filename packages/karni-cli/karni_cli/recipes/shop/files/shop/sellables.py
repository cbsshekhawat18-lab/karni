"""How the shop sells through karni-commerce: products are the kind "product".

karni-commerce imports this module at startup and calls the adapter for every cart
line and order line of the kind: its name, price and stock, and what happens to the
stock when an order holds it, is paid, is cancelled or is refunded. Commerce never
imports the shop. Change a rule here (a price per customer, a product that ships for
free) and every cart and checkout follows.

Stock goes through karni.capacity, so two buyers of the last item never both get it:

* checkout holds each line (``available - n``, refused when fewer are left);
* the payment takes it off the shelf (``stock - n``);
* a failed, cancelled or expired order gives the hold back (``available + n``);
* a paid order that is cancelled, or refunded with "back in stock", puts the items
  back (``stock + n`` and ``available + n``).

A product with ``backorders`` may be ordered past what is left: checkout holds what
is on the shelf and the rest waits for new stock. The line remembers how many it
held (``options["_held"]``), so only those are taken, given back or put back.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from django.db.models import F
from django.utils import timezone
from karni.capacity import CapacityExceeded, release, reserve
from karni_commerce.fulfilment import register_reporter
from karni_commerce.models import Order, OrderLine
from karni_commerce.sellables import Price, Sellable, refuse, register

from shop import events
from shop.models import Product, Shipment

SHIPMENT_WORDS = {
    "processing": "Being prepared",
    "shipped": "Shipped",
    "delivered": "Delivered",
    "cancelled": "Cancelled",
}


@register
class ProductSellable(Sellable):
    """A product of the shop's catalogue, sent to an address."""

    kind = "product"
    model = Product

    def key(self, item: Product) -> str:
        return str(item.pk)

    def name(self, item: Product, options: Mapping[str, Any]) -> str:
        return item.name

    def sku(self, item: Product, options: Mapping[str, Any]) -> str:
        return item.sku

    def url(self, item: Product) -> str:
        return f"/shop/products/{item.slug}"

    def image(self, item: Product) -> Any:
        return item.image

    def price(self, item: Product, options: Mapping[str, Any], buyer: Any) -> Price:
        current = item.current_price()
        return Price(unit=current, compare_at=item.price if item.on_sale() else None)

    def needs_shipping(self, item: Product, options: Mapping[str, Any]) -> bool:
        return True

    search_fields = ("name", "sku")

    def queryset(self) -> Any:
        return Product.objects.all()

    def available(self, item: Product, options: Mapping[str, Any]) -> int | None:
        if not item.active:
            return 0
        return None if item.backorders else int(item.available)

    def validate(
        self, item: Product, quantity: int, options: Mapping[str, Any], buyer: Any
    ) -> None:
        if not item.active:
            raise refuse(f"{item.name} is not for sale.")
        super().validate(item, quantity, options, buyer)

    def hold(self, line: OrderLine) -> None:
        product = Product.objects.get(pk=line.item)
        wanted = line.quantity
        if product.backorders:
            wanted = min(line.quantity, max(int(product.available), 0))
        try:
            if wanted:
                reserve(product, wanted, field="available")
        except CapacityExceeded:
            product.refresh_from_db()
            left = product.available
            raise refuse(
                f"{product.name}: only {left} left."
                if left
                else f"{product.name} is sold out."
            ) from None
        self._held(line, wanted)

    def release(self, line: OrderLine) -> None:
        held = self.held(line)
        if held:
            release(Product.objects.get(pk=line.item), held, field="available")

    def on_paid(self, line: OrderLine) -> None:
        held = self.held(line)
        if held:
            Product.objects.filter(pk=line.item).update(
                stock=F("stock") - held, updated_at=timezone.now()
            )
        product = Product.objects.get(pk=line.item)
        if product.runs_low():
            events.product_low_stock.send(sender=Product, product=product)

    def on_cancelled(self, line: OrderLine) -> None:
        self._back_on_the_shelf(line.item, self.held(line))

    def on_refunded(self, line: OrderLine, quantity: int, restock: bool) -> None:
        if restock:
            self._back_on_the_shelf(line.item, min(quantity, self.held(line)))

    def held(self, line: OrderLine) -> int:
        """How many of the line came off the shelf (all of it, unless backordered)."""
        return int((line.options or {}).get("_held", line.quantity))

    def _held(self, line: OrderLine, count: int) -> None:
        if count == line.quantity and "_held" not in (line.options or {}):
            return
        line.options = {**(line.options or {}), "_held": count}
        OrderLine.objects.filter(pk=line.pk).update(options=line.options)

    def _back_on_the_shelf(self, key: str, quantity: int) -> None:
        if quantity <= 0:
            return
        Product.objects.filter(pk=key).update(
            stock=F("stock") + quantity, updated_at=timezone.now()
        )
        release(Product.objects.get(pk=key), quantity, field="available")

    def coupon_keys(self, item: Product) -> dict[str, Any]:
        return {
            "categories": [
                str(pk) for pk in item.categories.values_list("pk", flat=True)
            ]
        }


@register_reporter
def shipments(order: Order) -> Iterator[dict[str, Any]]:
    """The order's parcel for its buyer's page: where it is, and its tracking number."""
    for shipment in Shipment.objects.filter(order=order).order_by("created_at"):
        detail = ""
        if shipment.tracking_number:
            carrier = f"{shipment.carrier} " if shipment.carrier else ""
            detail = f"{carrier}tracking {shipment.tracking_number}"
        yield {
            "title": "Parcel",
            "status": shipment.status,
            "label": SHIPMENT_WORDS.get(shipment.status, shipment.status),
            "detail": detail,
            "at": shipment.delivered_at or shipment.shipped_at or shipment.created_at,
        }
