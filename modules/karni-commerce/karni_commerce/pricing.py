"""Experimental. What an order costs: its lines, a coupon, shipping and tax, worked out once.

:func:`quote` is the one place totals are computed. The cart's page, the
checkout page (``POST carts/current/quote/``) and checkout itself call it, so
what a buyer sees is what the order stores.

1. Each line is priced by its kind's adapter (``Sellable.price``).
2. A coupon takes money off the lines it applies to: a percent of each, or a
   fixed amount shared between them by their price. A free-shipping coupon
   makes the shipping free instead.
3. Shipping, when a line is sent somewhere: the methods of the first zone that
   covers the address (:class:`ZoneShipping`). No zone at all means shipping is
   not charged.
4. Tax: each line's tax class at the rate for the address (:class:`RateTax`),
   and the shipping at the standard rate. Prices are entered without their tax,
   or with it when ``KARNI_COMMERCE_PRICES_INCLUDE_TAX`` is on (the tax is then
   the part of the price that is tax).

Override / escape hatch: ``KARNI_COMMERCE_SHIPPING`` and ``KARNI_COMMERCE_TAX``
name the classes that give the shipping methods and the tax rates (subclass
:class:`ZoneShipping` or :class:`RateTax`), and :func:`coupon_problem` and
:func:`coupon_applies` are module functions an app may call around.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from functools import cache
from typing import Any

from django.db.models import Q
from django.utils import timezone
from django.utils.module_loading import import_string

from karni_commerce import conf
from karni_commerce.models import (
    ZERO,
    Coupon,
    CouponUse,
    ShippingMethod,
    ShippingZone,
    TaxRate,
)

__all__ = [
    "MethodOption",
    "Quote",
    "QuoteLine",
    "RateTax",
    "TaxLine",
    "ZoneShipping",
    "coupon_applies",
    "coupon_problem",
    "find_coupon",
    "prices_include_tax",
    "quote",
    "shipping_backend",
    "tax_backend",
]

CENT = Decimal("0.01")
HUNDRED = Decimal("100")


def money(value: Any) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def prices_include_tax() -> bool:
    """Whether the adapters' prices include tax (``KARNI_COMMERCE_PRICES_INCLUDE_TAX``)."""
    return bool(conf.get("KARNI_COMMERCE_PRICES_INCLUDE_TAX"))


@dataclass
class QuoteLine:
    """One line as the quote prices it: what it is, its price, its discount and its tax."""

    kind: str
    item: str
    quantity: int
    options: dict[str, Any]
    unit: Decimal
    compare_at: Decimal | None = None
    tax_class: str = ""
    needs_shipping: bool = False
    coupon_keys: dict[str, Any] = field(default_factory=dict)
    name: str = ""
    sku: str = ""
    details: list[dict[str, str]] = field(default_factory=list)
    discount: Decimal = ZERO
    tax_rate: Decimal = ZERO
    tax: Decimal = ZERO
    tax_name: str = ""
    #: The deposit of one item (``Sellable.deposit``), or ``None`` when the line allows none.
    deposit: Decimal | None = None
    #: How long checkout may hold the line, in minutes (``Sellable.hold_minutes``), or ``None``.
    hold_minutes: int | None = None

    @property
    def line_total(self) -> Decimal:
        """The price of the line before its discount (as the prices are entered)."""
        return money(money(self.unit) * self.quantity)

    @property
    def total(self) -> Decimal:
        """What the buyer pays for the line: less its discount, with its tax."""
        base = self.line_total - self.discount
        return base if prices_include_tax() else base + self.tax


@dataclass(frozen=True)
class MethodOption:
    """A way to send the order, with what it costs this order."""

    id: str
    name: str
    kind: str
    cost: Decimal
    taxable: bool = True


@dataclass(frozen=True)
class TaxLine:
    name: str
    rate: Decimal
    amount: Decimal


@dataclass
class Quote:
    """The whole price of an order: lines, coupon, shipping, tax and the total."""

    currency: str
    lines: list[QuoteLine]
    prices_include_tax: bool
    coupon: Coupon | None = None
    coupon_problem: str = ""
    methods: list[MethodOption] = field(default_factory=list)
    method: MethodOption | None = None
    shipping_problem: str = ""
    shipping: Decimal = ZERO
    shipping_tax: Decimal = ZERO
    tax_lines: list[TaxLine] = field(default_factory=list)

    @property
    def needs_shipping(self) -> bool:
        return any(line.needs_shipping for line in self.lines)

    @property
    def subtotal(self) -> Decimal:
        return sum((line.line_total for line in self.lines), ZERO)

    @property
    def discount(self) -> Decimal:
        return sum((line.discount for line in self.lines), ZERO)

    @property
    def tax(self) -> Decimal:
        return sum((line.tax for line in self.lines), ZERO) + self.shipping_tax

    @property
    def total(self) -> Decimal:
        total = self.subtotal - self.discount + self.shipping
        if not self.prices_include_tax:
            total += self.tax
        return max(money(total), ZERO)

    @property
    def free_shipping(self) -> bool:
        return self.coupon is not None and self.coupon.kind == Coupon.Kind.FREE_SHIPPING

    @property
    def deposit(self) -> Decimal | None:
        """What the buyer may pay now and the rest later, or ``None`` when that is not offered.

        Offered when every line allows a deposit (a booking's): the lines' deposits
        times their quantities, never more than the total. ``None`` too when that comes
        to nothing, or to the whole total.
        """
        if not self.lines or any(line.deposit is None for line in self.lines):
            return None
        each = (money(line.deposit or ZERO) * line.quantity for line in self.lines)
        found = money(sum(each, ZERO))
        if found <= 0 or found >= self.total:
            return None
        return found


# -- coupons -------------------------------------------------------------------------------


def find_coupon(code: str) -> Coupon | None:
    """The coupon a buyer typed (any case), or ``None``."""
    text = str(code or "").strip().upper()
    return Coupon.objects.filter(code=text).first() if text else None


def _keys(values: Any) -> list[str]:
    """A coupon's keys: texts, or ``{"key": ..., "name": ...}`` as the staff's form keeps them."""
    found: list[str] = []
    for value in values or []:
        key = value.get("key") if isinstance(value, dict) else value
        if key not in (None, ""):
            found.append(str(key))
    return found


def coupon_applies(coupon: Coupon, line: QuoteLine) -> bool:
    """Whether ``coupon`` takes money off ``line``: its kinds, its items and its limits."""
    kinds = coupon.kind_list()
    if kinds and line.kind.lower() not in kinds:
        return False
    items = _keys(coupon.items)
    limits = {str(key): _keys(values) for key, values in (coupon.limits or {}).items()}
    limits = {key: values for key, values in limits.items() if values}
    if not items and not limits:
        return True
    if f"{line.kind}:{line.item}" in items:
        return True
    for key, wanted in limits.items():
        have = {str(value) for value in line.coupon_keys.get(key, []) or []}
        if have.intersection(wanted):
            return True
    return False


def _uses(coupon: Coupon) -> Any:
    """The uses that count: those of orders that were not cancelled."""
    return CouponUse.objects.filter(coupon=coupon).exclude(order__status__in=["cancelled"])


def coupon_problem(
    coupon: Coupon,
    lines: Sequence[QuoteLine],
    *,
    buyer: Any = None,
    email: str = "",
    now: datetime | None = None,
) -> str:
    """Why ``coupon`` cannot be used on these lines, in words, or ``""`` when it can."""
    moment = now or timezone.now()
    if not coupon.active:
        return "This coupon is not valid."
    if coupon.starts_at is not None and coupon.starts_at > moment:
        return "This coupon is not valid yet."
    if coupon.ends_at is not None and coupon.ends_at <= moment:
        return "This coupon has expired."
    matching = [line for line in lines if coupon_applies(coupon, line)]
    if not matching:
        return "This coupon does not apply to anything in your cart."
    subtotal = sum((line.line_total for line in lines), ZERO)
    if coupon.minimum_spend is not None and subtotal < Decimal(coupon.minimum_spend):
        return f"Spend at least {money(coupon.minimum_spend)} to use this coupon."
    if coupon.usage_limit is not None and _uses(coupon).count() >= coupon.usage_limit:
        return "This coupon has been used up."
    if coupon.usage_limit_per_person is not None:
        person = buyer if buyer is not None and getattr(buyer, "is_authenticated", False) else None
        mine = Q(email__iexact=email) if email else Q(pk__in=[])
        if person is not None:
            mine |= Q(user=person)
        if (email or person is not None) and _uses(coupon).filter(
            mine
        ).count() >= coupon.usage_limit_per_person:
            return "You have used this coupon already."
    return ""


def _apply_coupon(coupon: Coupon, lines: Sequence[QuoteLine]) -> None:
    matching = [line for line in lines if coupon_applies(coupon, line)]
    if coupon.kind == Coupon.Kind.PERCENT:
        share = min(Decimal(coupon.amount), HUNDRED) / HUNDRED
        for line in matching:
            line.discount = money(line.line_total * share)
    elif coupon.kind == Coupon.Kind.FIXED:
        base = sum((line.line_total for line in matching), ZERO)
        if base <= 0:
            return
        off = min(money(coupon.amount), base)
        left = off
        for index, line in enumerate(matching):
            last = index == len(matching) - 1
            part = left if last else min(money(off * line.line_total / base), left)
            line.discount = part
            left -= part


# -- shipping ------------------------------------------------------------------------------


class ZoneShipping:
    """Experimental. The shipping methods of the zone that covers the address.

    Override / escape hatch: subclass it, change :meth:`methods`, and name it
    in ``KARNI_COMMERCE_SHIPPING``.
    """

    def has_zones(self) -> bool:
        """Whether the business set up shipping at all (with no zone, shipping is not charged)."""
        return ShippingZone.objects.exists()

    def zone_for(self, address: Mapping[str, Any]) -> ShippingZone | None:
        country = str(address.get("country") or "")
        if not country:
            return None
        for zone in ShippingZone.objects.order_by("position", "name"):
            if zone.covers(
                country, str(address.get("region") or ""), str(address.get("postcode") or "")
            ):
                return zone
        return None

    def methods(self, address: Mapping[str, Any], goods: Decimal, free: bool) -> list[MethodOption]:
        """The methods for ``address``, priced for ``goods`` (the items less their discount).

        ``free``: a free-shipping coupon applies, so every method costs nothing.
        """
        zone = self.zone_for(address)
        if zone is None:
            return []
        found: list[MethodOption] = []
        rows = ShippingMethod.objects.filter(zone=zone, active=True).order_by("position", "name")
        for method in rows:
            reached = method.free_above is not None and goods >= Decimal(method.free_above)
            if (
                method.kind == ShippingMethod.Kind.FREE
                and method.free_above is not None
                and not reached
            ):
                continue
            cost = (
                ZERO
                if (free or reached or method.kind == ShippingMethod.Kind.FREE)
                else money(method.cost)
            )
            found.append(
                MethodOption(str(method.pk), method.name, method.kind, cost, method.taxable)
            )
        return found


class RateTax:
    """Experimental. The tax rates of :class:`~karni_commerce.models.TaxRate`, most specific first.

    Override / escape hatch: subclass it, change :meth:`rate`, and name it in
    ``KARNI_COMMERCE_TAX``.
    """

    def rate(self, tax_class: str, address: Mapping[str, Any]) -> TaxRate | None:
        """The rate of ``tax_class`` at ``address``: country and region, country, or anywhere."""
        country = str(address.get("country") or "").upper()
        region = str(address.get("region") or "").strip().upper()
        rows = TaxRate.objects.filter(tax_class=tax_class).filter(
            Q(country="") | Q(country=country)
        )
        best: TaxRate | None = None
        best_score = -1
        for row in rows:
            if row.region and row.region != region:
                continue
            score = (2 if row.country else 0) + (1 if row.region else 0)
            if score > best_score:
                best, best_score = row, score
        return best


@cache
def _load(path: str) -> Any:
    return import_string(path)


def shipping_backend() -> ZoneShipping:
    """The ``KARNI_COMMERCE_SHIPPING`` class, made once per call."""
    return _load(str(conf.get("KARNI_COMMERCE_SHIPPING")))()


def tax_backend() -> RateTax:
    """The ``KARNI_COMMERCE_TAX`` class, made once per call."""
    return _load(str(conf.get("KARNI_COMMERCE_TAX")))()


def _tax_of(base: Decimal, rate: Decimal, inclusive: bool) -> Decimal:
    if rate <= 0 or base <= 0:
        return ZERO
    if inclusive:
        return money(base * rate / (HUNDRED + rate))
    return money(base * rate / HUNDRED)


# -- the quote -----------------------------------------------------------------------------


def quote(
    lines: list[QuoteLine],
    *,
    currency: str,
    buyer: Any = None,
    email: str = "",
    address: Mapping[str, Any] | None = None,
    coupon: Coupon | None = None,
    method: str | None = None,
) -> Quote:
    """Price ``lines`` for ``address`` (where they go, else where the buyer is billed).

    ``coupon`` is applied when it may be (else ``coupon_problem`` says why),
    and ``method`` is the id of the shipping method chosen (blank: the first
    one offered). Nothing here writes to the database.
    """
    place = dict(address or {})
    inclusive = prices_include_tax()
    result = Quote(currency=currency, lines=lines, prices_include_tax=inclusive)
    if coupon is not None:
        problem = coupon_problem(coupon, lines, buyer=buyer, email=email)
        if problem:
            result.coupon_problem = problem
        else:
            result.coupon = coupon
            _apply_coupon(coupon, lines)
    if result.needs_shipping:
        backend = shipping_backend()
        if backend.has_zones():
            goods = result.subtotal - result.discount
            result.methods = backend.methods(place, goods, result.free_shipping)
            if place.get("country") and not result.methods:
                result.shipping_problem = f"We do not send orders to {place['country']} yet."
            chosen = next((option for option in result.methods if option.id == method), None)
            if method and chosen is None and result.methods:
                result.shipping_problem = "Choose one of the ways to send it."
            result.method = chosen or (result.methods[0] if result.methods and not method else None)
            if result.method is not None:
                result.shipping = result.method.cost
    taxes = tax_backend()
    found: dict[tuple[str, Decimal], Decimal] = {}
    if place.get("country"):
        for line in lines:
            rate = taxes.rate(line.tax_class, place)
            if rate is None:
                continue
            line.tax_rate = Decimal(rate.rate)
            line.tax_name = rate.name
            line.tax = _tax_of(line.line_total - line.discount, line.tax_rate, inclusive)
            if line.tax:
                key = (rate.name, Decimal(rate.rate))
                found[key] = found.get(key, ZERO) + line.tax
        if result.method is not None and result.method.taxable and result.shipping > 0:
            rate = taxes.rate("", place)
            if rate is not None and rate.shipping:
                result.shipping_tax = _tax_of(result.shipping, Decimal(rate.rate), inclusive)
                if result.shipping_tax:
                    key = (rate.name, Decimal(rate.rate))
                    found[key] = found.get(key, ZERO) + result.shipping_tax
    result.tax_lines = [
        TaxLine(name, rate, money(amount)) for (name, rate), amount in found.items()
    ]
    return result
