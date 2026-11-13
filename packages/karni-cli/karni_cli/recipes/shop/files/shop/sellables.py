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

A digital product sends nothing and has no stock to hold: once paid, its buyer gets a
signed link to each of its files (shop/services.py, ``grant_downloads``).

A product with active variations (sizes, colours) is bought by one of them: the line's
options name it (``{"variation": "<id>"}``), and its price, SKU and stock are the
variation's. Two variations of one product are two lines of the cart.
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
from shop.models import Category, Product, Shipment, Variation

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

    search_fields = ("name", "sku")

    def queryset(self) -> Any:
        return Product.objects.all()

    # -- variations ------------------------------------------------------------------

    def variations(self, item: Product) -> list[Variation]:
        """The product's variations for sale, in their order (cached on the product)."""
        found = getattr(item, "_shop_variations", None)
        if found is None:
            found = list(
                Variation.objects.filter(product=item, active=True)
                .prefetch_related("values__attribute")
                .order_by("position", "sku")
            )
            item._shop_variations = found  # type: ignore[attr-defined]
        return found

    def variation(self, item: Product, options: Mapping[str, Any]) -> Variation | None:
        """The variation the options name, or ``None`` (a product sold as it is)."""
        wanted = str(options.get("variation") or "")
        if not wanted:
            return None
        return next(
            (row for row in self.variations(item) if str(row.pk) == wanted), None
        )

    def clean_options(
        self, item: Product, options: Mapping[str, Any]
    ) -> dict[str, Any]:
        """A product with variations needs one of them, and keeps nothing else."""
        choices = self.variations(item)
        if not choices:
            return {}
        chosen = self.variation(item, options)
        if chosen is None:
            if options.get("variation"):
                raise refuse(f"{item.name} does not come that way.", field="options")
            raise refuse(f"Choose the options of {item.name}.", field="options")
        return {"variation": str(chosen.pk)}

    def option_key(self, item: Product, options: Mapping[str, Any]) -> str:
        return str(options.get("variation") or "")

    def choices(self, item: Product) -> list[dict[str, Any]]:
        found = self.variations(item)
        return [{"variation": str(row.pk)} for row in found] if found else [{}]

    def details(
        self, item: Product, options: Mapping[str, Any]
    ) -> list[dict[str, str]]:
        chosen = self.variation(item, options)
        return chosen.details() if chosen is not None else []

    # -- what it is and costs ----------------------------------------------------------

    def name(self, item: Product, options: Mapping[str, Any]) -> str:
        chosen = self.variation(item, options)
        return f"{item.name}, {chosen.label()}" if chosen is not None else item.name

    def sku(self, item: Product, options: Mapping[str, Any]) -> str:
        chosen = self.variation(item, options)
        return chosen.sku if chosen is not None else item.sku

    def url(self, item: Product) -> str:
        return f"/shop/products/{item.slug}"

    def image(self, item: Product) -> Any:
        return item.image

    def price(self, item: Product, options: Mapping[str, Any], buyer: Any) -> Price:
        chosen = self.variation(item, options)
        if chosen is not None:
            return Price(
                unit=chosen.current_price(),
                compare_at=chosen.regular_price() if chosen.on_sale() else None,
            )
        current = item.current_price()
        return Price(unit=current, compare_at=item.price if item.on_sale() else None)

    def needs_shipping(self, item: Product, options: Mapping[str, Any]) -> bool:
        return not item.digital

    def available(self, item: Product, options: Mapping[str, Any]) -> int | None:
        if not item.active:
            return 0
        if item.backorders or item.digital:
            return None
        chosen = self.variation(item, options)
        if chosen is not None:
            return int(chosen.available)
        if self.variations(item):
            return sum(int(row.available) for row in self.variations(item))
        return int(item.available)

    def validate(
        self, item: Product, quantity: int, options: Mapping[str, Any], buyer: Any
    ) -> None:
        if not item.active:
            raise refuse(f"{item.name} is not for sale.")
        super().validate(item, quantity, options, buyer)

    # -- the stock ---------------------------------------------------------------------

    def _digital(self, line: OrderLine) -> bool:
        if (line.options or {}).get("variation"):
            return False
        return Product.objects.filter(pk=line.item, digital=True).exists()

    def _stocked(self, line: OrderLine) -> Product | Variation:
        """The row whose stock the line moves: its variation, else its product."""
        wanted = (line.options or {}).get("variation")
        if wanted:
            return Variation.objects.get(pk=wanted)
        return Product.objects.get(pk=line.item)

    def hold(self, line: OrderLine) -> None:
        if self._digital(line):
            self._held(line, 0)  # a file has no stock: nothing to hold or give back
            return
        row = self._stocked(line)
        product = row if isinstance(row, Product) else row.product
        wanted = line.quantity
        if product.backorders:
            wanted = min(line.quantity, max(int(row.available), 0))
        try:
            if wanted:
                reserve(row, wanted, field="available")
        except CapacityExceeded:
            row.refresh_from_db()
            left = row.available
            raise refuse(
                f"{line.name}: only {left} left."
                if left
                else f"{line.name} is sold out."
            ) from None
        self._held(line, wanted)

    def release(self, line: OrderLine) -> None:
        held = self.held(line)
        if held:
            release(self._stocked(line), held, field="available")

    def on_paid(self, line: OrderLine) -> None:
        held = self.held(line)
        if held == 0 and self._digital(line):
            return
        row = self._stocked(line)
        if held:
            type(row).objects.filter(pk=row.pk).update(
                stock=F("stock") - held, updated_at=timezone.now()
            )
            row.refresh_from_db()
        product = row if isinstance(row, Product) else row.product
        if row.runs_low():
            events.product_low_stock.send(
                sender=Product,
                product=product,
                variation=None if isinstance(row, Product) else row,
            )

    def on_cancelled(self, line: OrderLine) -> None:
        self._back_on_the_shelf(line, self.held(line))

    def on_refunded(self, line: OrderLine, quantity: int, restock: bool) -> None:
        if restock:
            self._back_on_the_shelf(line, min(quantity, self.held(line)))

    def held(self, line: OrderLine) -> int:
        """How many of the line came off the shelf (all of it, unless backordered)."""
        return int((line.options or {}).get("_held", line.quantity))

    def _held(self, line: OrderLine, count: int) -> None:
        if count == line.quantity and "_held" not in (line.options or {}):
            return
        line.options = {**(line.options or {}), "_held": count}
        OrderLine.objects.filter(pk=line.pk).update(options=line.options)

    def _back_on_the_shelf(self, line: OrderLine, quantity: int) -> None:
        if quantity <= 0:
            return
        row = self._stocked(line)
        type(row).objects.filter(pk=row.pk).update(
            stock=F("stock") + quantity, updated_at=timezone.now()
        )
        row.refresh_from_db()
        release(row, quantity, field="available")

    def coupon_keys(self, item: Product) -> dict[str, Any]:
        """Its categories and every category above them: a coupon for Kitchen takes off
        Cookware too."""
        found: set[str] = set()
        for category in item.categories.all():
            node: Category | None = category
            while node is not None:
                found.add(str(node.pk))
                node = node.parent
        return {"categories": sorted(found)}


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


@register_reporter
def downloads(order: Order) -> Iterator[dict[str, Any]]:
    """The order's files for its buyer's page: the link, and how many downloads are left."""
    from shop.models import Download
    from shop.services import download_link, download_problem

    for row in Download.objects.filter(order=order).select_related("file", "order"):
        problem = download_problem(row)
        left = None if row.limit is None else max(row.limit - row.downloads, 0)
        detail = problem or (
            f"{left} of {row.limit} downloads left"
            if left is not None
            else "Download it"
        )
        yield {
            "title": "Download",
            "status": "stopped" if problem else "ready",
            "label": row.file.name,
            "detail": detail,
            "at": row.last_at,
            "link": "" if problem else download_link(row),
            "link_label": f"Download {row.file.name}",
        }
