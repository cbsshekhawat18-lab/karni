"""The test app's kinds: gadgets (stock, shipping), workshop seats (no late refund) and
bookings of a slot (a 15-minute hold, a deposit, a refund policy by time before the start)."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import F
from karni.capacity import CapacityExceeded, release, reserve

from karni_commerce.models import OrderLine
from karni_commerce.sellables import Price, Sellable, refuse, register
from tests.testapp.models import Booking, Gadget, Slot, Workshop


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

    def details(self, item: Gadget, options: Any) -> list[dict[str, str]]:
        colour = options.get("colour")
        return [{"label": "Colour", "value": str(colour)}] if colour else []

    def coupon_keys(self, item: Gadget) -> dict[str, Any]:
        return {"shelves": [item.sku[:3]] if item.sku else []}

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

    def on_cancelled(self, line: OrderLine) -> None:
        self._free(line.item, line.quantity - line.quantity_refunded)

    def on_refunded(self, line: OrderLine, quantity: int, restock: bool) -> None:
        self._free(line.item, quantity)  # a refunded seat is free again

    def _free(self, key: str, quantity: int) -> None:
        Workshop.objects.filter(pk=key).update(enrolled=F("enrolled") - quantity)
        release(Workshop.objects.get(pk=key), quantity)

    def refund_limit(self, line: OrderLine, now: datetime) -> Decimal:
        workshop = Workshop.objects.get(pk=line.item)
        return Decimal("0") if workshop.starts_at <= now else super().refund_limit(line, now)


@register
class BookingSellable(Sellable):
    """A dry run of the booking recipe's adapter: kind ``booking``.

    Checkout makes a tentative booking and holds the seats for 15 minutes. The
    deposit (or the whole payment) confirms it. A refund frees the seats, in full
    until a day before the start and nothing after. The slot is freed when the
    order is not paid in time.
    """

    kind = "booking"
    model = Slot
    search_fields = ("title",)

    def name(self, item: Slot, options: Any) -> str:
        return f"Booking: {item.title}"

    def details(self, item: Slot, options: Any) -> list[dict[str, str]]:
        return [{"label": "When", "value": item.starts_at.strftime("%d %b %Y, %H:%M")}]

    def price(self, item: Slot, options: Any, buyer: Any) -> Price:
        return Price(unit=item.price)

    def available(self, item: Slot, options: Any) -> int:
        return int(item.free_seats)

    def allows_deposit(self, item: Slot, options: Any) -> bool:
        return item.deposit > 0

    def deposit(self, item: Slot, options: Any) -> Decimal:
        return Decimal(item.deposit)

    def hold_minutes(self, item: Slot, options: Any) -> int:
        return 15

    def validate(self, item: Slot, quantity: int, options: Any, buyer: Any) -> None:
        from django.utils import timezone

        if item.starts_at <= timezone.now():
            raise refuse(f"{item.title} has started.")
        super().validate(item, quantity, options, buyer)

    def hold(self, line: OrderLine) -> None:
        slot = Slot.objects.get(pk=line.item)
        try:
            reserve(slot, line.quantity)
        except CapacityExceeded:
            raise refuse(f"{slot.title} is fully booked.") from None
        Booking.objects.update_or_create(
            order_line=str(line.pk),
            defaults={
                "slot": slot,
                "seats": line.quantity,
                "status": Booking.Status.HELD,
                "expires_at": line.order.hold_until,
            },
        )

    def release(self, line: OrderLine) -> None:
        release(Slot.objects.get(pk=line.item), line.quantity)
        Booking.objects.filter(order_line=str(line.pk)).update(
            status=Booking.Status.RELEASED, expires_at=None
        )

    def on_paid(self, line: OrderLine) -> None:
        Booking.objects.filter(order_line=str(line.pk)).update(
            status=Booking.Status.CONFIRMED, expires_at=None
        )

    def on_cancelled(self, line: OrderLine) -> None:
        release(Slot.objects.get(pk=line.item), line.quantity - line.quantity_refunded)
        Booking.objects.filter(order_line=str(line.pk)).update(status=Booking.Status.CANCELLED)

    def on_refunded(self, line: OrderLine, quantity: int, restock: bool) -> None:
        release(Slot.objects.get(pk=line.item), quantity)  # the seats are free again
        if line.quantity_refunded >= line.quantity:
            Booking.objects.filter(order_line=str(line.pk)).update(status=Booking.Status.CANCELLED)

    def refund_limit(self, line: OrderLine, now: datetime) -> Decimal:
        slot = Slot.objects.get(pk=line.item)
        if slot.starts_at - now < timedelta(days=1):
            return Decimal("0")
        return super().refund_limit(line, now)
