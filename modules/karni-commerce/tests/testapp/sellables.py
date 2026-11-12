"""The test app's two kinds: gadgets (stock, shipping) and workshop seats (no late refund)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from django.db.models import F
from karni.capacity import CapacityExceeded, release, reserve

from karni_commerce.models import OrderLine
from karni_commerce.sellables import Price, Sellable, refuse, register
from tests.testapp.models import Gadget, Workshop


@register
class GadgetSellable(Sellable):
    kind = "gadget"
    model = Gadget
    search_fields = ("name", "sku")

    def name(self, item: Gadget, options: Any) -> str:
        colour = options.get("colour")
        return f"{item.name}, {colour}" if colour else item.name

    def sku(self, item: Gadget, options: Any) -> str:
        return item.sku

    def url(self, item: Gadget) -> str:
        return f"/gadgets/{item.pk}"

    def price(self, item: Gadget, options: Any, buyer: Any) -> Price:
        if item.sale_price is not None:
            return Price(unit=item.sale_price, compare_at=item.price)
        return Price(unit=item.price)

    def needs_shipping(self, item: Gadget, options: Any) -> bool:
        return True

    def available(self, item: Gadget, options: Any) -> int:
        return int(item.available)

    def hold(self, line: OrderLine) -> None:
        gadget = Gadget.objects.get(pk=line.item)
        try:
            reserve(gadget, line.quantity)
        except CapacityExceeded:
            raise refuse(f"{gadget.name}: only {gadget.available} left.") from None

    def release(self, line: OrderLine) -> None:
        release(Gadget.objects.get(pk=line.item), line.quantity)

    def on_paid(self, line: OrderLine) -> None:
        Gadget.objects.filter(pk=line.item).update(stock=F("stock") - line.quantity)

    def on_cancelled(self, line: OrderLine) -> None:
        self._back(line.item, line.quantity)

    def on_refunded(self, line: OrderLine, quantity: int, restock: bool) -> None:
        if restock:
            self._back(line.item, quantity)

    def _back(self, key: str, quantity: int) -> None:
        Gadget.objects.filter(pk=key).update(stock=F("stock") + quantity)
        release(Gadget.objects.get(pk=key), quantity)


@register
class SeatSellable(Sellable):
    """The second kind: a seat, enrolled when paid, never refunded once the workshop started."""

    kind = "seat"
    model = "testapp.Workshop"

    def name(self, item: Workshop, options: Any) -> str:
        return f"Seat at {item.title}"

    def price(self, item: Workshop, options: Any, buyer: Any) -> Price:
        return Price(unit=item.price)

    def available(self, item: Workshop, options: Any) -> int:
        return int(item.free_seats)

    def validate(self, item: Workshop, quantity: int, options: Any, buyer: Any) -> None:
        from django.utils import timezone

        if item.starts_at <= timezone.now():
            raise refuse(f"{item.title} has started.")
        super().validate(item, quantity, options, buyer)

    def hold(self, line: OrderLine) -> None:
        reserve(Workshop.objects.get(pk=line.item), line.quantity)

    def release(self, line: OrderLine) -> None:
        release(Workshop.objects.get(pk=line.item), line.quantity)

    def on_paid(self, line: OrderLine) -> None:
        Workshop.objects.filter(pk=line.item).update(enrolled=F("enrolled") + line.quantity)

    def refund_limit(self, line: OrderLine, now: datetime) -> Decimal:
        workshop = Workshop.objects.get(pk=line.item)
        return Decimal("0") if workshop.starts_at <= now else super().refund_limit(line, now)
