"""Experimental. The order path: the cart, checkout, the settlement, cancelling and refunds.

Every change goes through these functions, each in one transaction, and
every price and total is computed here from the sellable adapters
(:mod:`karni_commerce.sellables`), never taken from the client.

* :func:`set_line` puts an item in a cart, after the adapter's ``validate``.
* :func:`checkout` turns a cart into a pending :class:`Order`: each line's
  name, SKU and price are copied, every line is held (``Sellable.hold``) or
  none is, and the order holds them for ``KARNI_COMMERCE_HOLD_MINUTES``.
* :func:`open_payment` starts the payment at the provider for what is due
  now (the deposit, the balance or the whole total), or answers the one still
  open (its address is kept in the payment's ``metadata["url"]``). An order
  whose total is zero is paid when it is placed, with no payment, whatever it
  sells.
* :func:`settle` moves the order when karni-payments reports its payment
  (:mod:`karni_commerce.listeners`): paid (``Sellable.on_paid``), part paid by
  its deposit (``on_paid`` too: the deposit secures the lines), or failed
  (``Sellable.release``). Money that arrives for an order that stopped
  waiting goes back at once.
* :func:`request_balance` sends the buyer of a part-paid order the link to pay
  the rest.
* :func:`cancel`, :func:`refund` and :func:`release_expired` are the other
  moves. :func:`place_manual_order` is staff placing an order for a buyer (a
  phone order), and :func:`add_note` a note on an order. A refund by lines or
  by amount settles when the provider confirms it (``Sellable.on_refunded``,
  with the items back on the shelf when asked).

Each move sends its signal from :mod:`karni_commerce.events`.

Override / escape hatch: every function is a plain module-level function, so
an app calls its own around them. ``KARNI_COMMERCE_NUMBER`` replaces the
order numbers, and the adapters decide everything about their items.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.utils import timezone
from django.utils.module_loading import import_string
from karni import preferences
from karni.events import publish
from karni_payments.models import Payment, Refund
from karni_payments.services import create_checkout, create_refund, refunded_amount
from rest_framework.exceptions import ValidationError

from karni_commerce import conf, events, pricing
from karni_commerce.models import (
    ZERO,
    Cart,
    CartLine,
    Coupon,
    CouponUse,
    Invoice,
    Order,
    OrderLine,
    OrderNote,
    OrderPayment,
    OrderRefund,
    new_key,
)
from karni_commerce.sellables import Price, Sellable, adapter_for, hold_of, kinds, refuse

__all__ = [
    "PricedLine",
    "add_note",
    "buyer_person",
    "apply_coupon",
    "cancel",
    "cart_lines",
    "checkout",
    "claim_orders",
    "find_cart",
    "merge",
    "next_number",
    "open_payment",
    "order_link",
    "place_manual_order",
    "place_order",
    "quote_cart",
    "request_balance",
    "quote_line",
    "refund",
    "release_expired",
    "set_line",
    "settle",
    "settle_refund",
]

logger = logging.getLogger(__name__)

CENT = Decimal("0.01")
#: The order states in which the buyer's money is in, and the items taken.
PAID_STATES = ("paid", "part_paid", "part_refunded")


def money(value: Any) -> Decimal:
    """``value`` as an amount of the currency: two places, half up."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def max_quantity() -> int:
    return int(conf.get("KARNI_COMMERCE_MAX_QUANTITY"))


def _user(user: Any) -> Any:
    """``user`` when signed in, else ``None``."""
    return user if user is not None and getattr(user, "is_authenticated", False) else None


# -- the cart ------------------------------------------------------------------------------


@dataclass
class PricedLine:
    """A cart line with its item and price today, or the reason it cannot be bought."""

    line: CartLine
    adapter: Sellable | None
    item: Any
    price: Price | None
    problem: str = ""
    name: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    details: list[dict[str, str]] = field(default_factory=list)

    @property
    def unit_price(self) -> Decimal:
        return money(self.price.unit) if self.price is not None else ZERO

    @property
    def line_total(self) -> Decimal:
        return money(self.unit_price * self.line.quantity)


def find_cart(user: Any, token: str | None, *, create: bool = False) -> Cart | None:
    """The signed-in person's cart, or the visitor's cart its token names (made when asked)."""
    person = _user(user)
    if person is not None:
        cart = Cart.objects.filter(user=person).order_by("created_at").first()
        if cart is None and create:
            cart = Cart.objects.create(user=person)
        return cart
    if token:
        found = Cart.objects.filter(user__isnull=True, token=token).first()
        if found is not None:
            return found
    return Cart.objects.create() if create else None


def _problem(adapter: Sellable, item: Any, quantity: int, options: Any, buyer: Any) -> str:
    try:
        adapter.validate(item, quantity, options, buyer)
    except ValidationError as exc:
        detail: Any = exc.detail
        while isinstance(detail, dict | list) and detail:
            detail = next(iter(detail.values())) if isinstance(detail, dict) else detail[0]
        return str(detail)
    return ""


def cart_lines(cart: Cart | None, buyer: Any = None) -> list[PricedLine]:
    """Each line of ``cart`` priced today, with what stops it from being bought.

    One query for the lines and one per kind for the items, however many lines.
    """
    if cart is None:
        return []
    rows = list(cart.lines.order_by("created_at", "pk"))
    by_kind: dict[str, list[CartLine]] = {}
    for row in rows:
        by_kind.setdefault(row.kind, []).append(row)
    known = kinds()
    items: dict[tuple[str, str], Any] = {}
    for kind, lines in by_kind.items():
        adapter = known.get(kind)
        if adapter is not None:
            for key, item in adapter.get_many(line.item for line in lines).items():
                items[(kind, key)] = item
    priced: list[PricedLine] = []
    person = _user(buyer)
    for row in rows:
        adapter = known.get(row.kind)
        item = items.get((row.kind, row.item))
        if adapter is None or item is None:
            priced.append(PricedLine(row, adapter, None, None, "No longer for sale.", "?"))
            continue
        priced.append(
            PricedLine(
                row,
                adapter,
                item,
                adapter.price(item, row.options, person),
                _problem(adapter, item, row.quantity, row.options, person),
                adapter.name(item, row.options),
                details=adapter.details(item, row.options),
            )
        )
    return priced


def set_line(
    cart: Cart,
    kind: str,
    key: str,
    quantity: int,
    options: Mapping[str, Any] | None = None,
    *,
    buyer: Any = None,
    add: bool = False,
) -> CartLine | None:
    """Put ``quantity`` of the item in ``cart`` (``add``: on top of what is there; 0 removes it).

    The cart's ``touched_at`` moves: a cart nobody touches for a while is abandoned.

    :raises ValidationError: for an unknown kind or item, more than
        ``KARNI_COMMERCE_MAX_QUANTITY``, or a line the adapter refuses.
    """
    found = _set_line(cart, kind, key, quantity, options, buyer=buyer, add=add)
    cart.touched_at = timezone.now()
    Cart.objects.filter(pk=cart.pk).update(touched_at=cart.touched_at)
    return found


def _set_line(
    cart: Cart,
    kind: str,
    key: str,
    quantity: int,
    options: Mapping[str, Any] | None = None,
    *,
    buyer: Any = None,
    add: bool = False,
) -> CartLine | None:
    adapter = adapter_for(kind)
    item = adapter.get(str(key))
    if item is None:
        raise refuse("Nothing like that is for sale here.")
    if int(quantity) <= 0 and not add:
        # Taking a line out needs no valid options: the line's own are enough.
        variant = adapter.option_key(item, dict(options or {}))
        CartLine.objects.filter(
            cart=cart, kind=kind, item=adapter.key(item), variant=variant
        ).delete()
        return None
    chosen = adapter.clean_options(item, dict(options or {}))
    variant = adapter.option_key(item, chosen)
    current = CartLine.objects.filter(
        cart=cart, kind=kind, item=adapter.key(item), variant=variant
    ).first()
    wanted = int(quantity) + (current.quantity if add and current is not None else 0)
    if wanted <= 0:
        if current is not None:
            current.delete()
        return None
    if wanted > max_quantity():
        raise refuse(f"At most {max_quantity()} of one item.", field="quantity")
    adapter.validate(item, wanted, chosen, _user(buyer))
    if current is None:
        return CartLine.objects.create(
            cart=cart,
            kind=kind,
            item=adapter.key(item),
            variant=variant,
            quantity=wanted,
            options=chosen,
        )
    current.quantity = wanted
    current.options = chosen
    current.save(update_fields=["quantity", "options", "updated_at"])
    return current


def apply_coupon(cart: Cart, code: str, *, buyer: Any = None, email: str = "") -> Coupon | None:
    """Put the coupon ``code`` on ``cart`` (blank takes it off).

    :raises ValidationError: for a code that is not a coupon, or one that
        cannot be used on this cart now (expired, used up, nothing it applies to).
    """
    text = str(code or "").strip()
    if not text:
        cart.coupon = None
        cart.save(update_fields=["coupon", "updated_at"])
        return None
    coupon = pricing.find_coupon(text)
    if coupon is None:
        raise refuse("No coupon has that code.", field="code")
    found = [quote_line_of(row) for row in cart_lines(cart, buyer) if row.problem == ""]
    lines = [line for line in found if line is not None]
    problem = pricing.coupon_problem(coupon, lines, buyer=_user(buyer), email=email)
    if problem:
        raise refuse(problem, field="code")
    cart.coupon = coupon
    cart.save(update_fields=["coupon", "updated_at"])
    return coupon


def quote_line(
    adapter: Sellable, item: Any, quantity: int, options: Mapping[str, Any], buyer: Any
) -> pricing.QuoteLine:
    """One line priced by its adapter, as :func:`karni_commerce.pricing.quote` takes it."""
    price = adapter.price(item, options, _user(buyer))
    deposit = (
        money(adapter.deposit(item, options)) if adapter.allows_deposit(item, options) else None
    )
    return pricing.QuoteLine(
        kind=adapter.kind,
        item=adapter.key(item),
        quantity=int(quantity),
        options=dict(options),
        unit=money(price.unit),
        compare_at=money(price.compare_at) if price.compare_at else None,
        tax_class=price.tax_class,
        needs_shipping=adapter.needs_shipping(item, options),
        coupon_keys=adapter.coupon_keys(item),
        name=adapter.name(item, options)[:200],
        sku=adapter.sku(item, options)[:64],
        details=adapter.details(item, options),
        deposit=deposit,
        hold_minutes=hold_of(adapter, item, options),
    )


def quote_line_of(row: PricedLine) -> pricing.QuoteLine | None:
    """A cart line as a quote line (``None`` when its item is gone)."""
    if row.adapter is None or row.item is None:
        return None
    return quote_line(row.adapter, row.item, row.line.quantity, row.line.options, None)


def quote_cart(
    cart: Cart | None,
    *,
    buyer: Any = None,
    email: str = "",
    address: Mapping[str, Any] | None = None,
    method: str | None = None,
) -> pricing.Quote:
    """What ``cart`` comes to now: its coupon, the shipping for ``address`` and the tax."""
    rows = cart_lines(cart, buyer)
    lines = [line for line in (quote_line_of(row) for row in rows) if line is not None]
    return pricing.quote(
        lines,
        currency=conf.currency(),
        buyer=_user(buyer),
        email=email,
        address=address,
        coupon=cart.coupon if cart is not None else None,
        method=method,
    )


@transaction.atomic
def merge(user: Any, token: str | None) -> Cart:
    """The visitor's cart joins the signed-in person's cart.

    Quantities add up, never past what an adapter allows: a line that no
    longer fits is kept at the most it can hold, or dropped. Guest orders
    placed with the person's verified email become theirs too.
    """
    cart = find_cart(user, None, create=True)
    assert cart is not None
    visitor = Cart.objects.filter(user__isnull=True, token=token).first() if token else None
    if visitor is not None and visitor.pk != cart.pk:
        for line in visitor.lines.all():
            current = CartLine.objects.filter(cart=cart, kind=line.kind, item=line.item).first()
            wanted = min(line.quantity + (current.quantity if current else 0), max_quantity())
            while wanted > 0:
                try:
                    with transaction.atomic():
                        set_line(cart, line.kind, line.item, wanted, line.options, buyer=user)
                    break
                except ValidationError:
                    wanted -= 1
        visitor.lines.all().delete()
        visitor.delete()
        events.cart_merged.send(sender=Cart, cart=cart, user=user)
    claim_orders(user)
    return cart


def claim_orders(user: Any) -> list[Order]:
    """The guest orders placed with ``user``'s email, once that email is verified, become theirs."""
    if not getattr(user, "email_verified", False) or not getattr(user, "email", ""):
        return []
    found = list(Order.objects.filter(user__isnull=True, email__iexact=user.email))
    for order in found:
        order.user = user
        order.save(update_fields=["user", "updated_at"])
    if found:
        events.orders_claimed.send(sender=Order, user=user, orders=found)
    return found


# -- checkout ------------------------------------------------------------------------------


def next_number(order: Order) -> int:
    """The default ``KARNI_COMMERCE_NUMBER``: one more than the highest, from the first number."""
    highest = Order.objects.without("soft_delete", reason="numbers are never reused").aggregate(
        highest=models.Max("number")
    )["highest"]
    first = int(conf.get("KARNI_COMMERCE_FIRST_NUMBER"))
    return max(int(highest or 0) + 1, first)


def _number(order: Order) -> int:
    path = str(conf.get("KARNI_COMMERCE_NUMBER") or "")
    numbering = import_string(path) if path else next_number
    return int(numbering(order))


def _save_new(order: Order) -> Order:
    for _attempt in range(5):
        order.number = _number(order)
        order.reference = str(order.number)
        try:
            with transaction.atomic():
                order.save()
            return order
        except IntegrityError:
            order.pk = None
            order._state.adding = True
            continue  # another checkout took the number at the same moment
    raise ValidationError({"number": ["Too many orders at once. Try again."]})


def buyer_person(*, user: Any = None, email: str = "", name: str = "", phone: str = "") -> Any:
    """The :class:`karni.people.models.Person` who buys: found or made by ``karni.people.resolve``.

    A signed-in buyer is the person linked to their account (or the person with
    their email). A guest is the person with the email they typed. Blank names and
    phone on the person are filled from what checkout knows, never overwritten.
    """
    from karni import people

    return people.resolve(
        user=_user(user),
        email=str(email or "").strip() or None,
        name=str(name or "").strip() or None,
        phone=str(phone or "").strip() or None,
        source="karni_commerce",
    )


def hold_minutes() -> int:
    """How long checkout holds an order's items for payment (``KARNI_COMMERCE_HOLD_MINUTES``)."""
    return int(conf.get("KARNI_COMMERCE_HOLD_MINUTES"))


def shortest_hold(lines: Iterable[pricing.QuoteLine], minutes: int | None = None) -> int:
    """How long an order of ``lines`` is held: ``minutes`` (the project's hold), or a line's
    shorter hold (``Sellable.hold_minutes``, a booking slot's 15)."""
    found = [line.hold_minutes for line in lines if line.hold_minutes is not None]
    return min([int(minutes if minutes is not None else hold_minutes()), *found])


@transaction.atomic
def priced_lines(
    lines: Sequence[tuple[str, str, int, Mapping[str, Any]]], buyer: Any = None
) -> list[pricing.QuoteLine]:
    """``lines`` (``(kind, key, quantity, options)``) checked and priced by their adapters.

    :raises ValidationError: for an item that is gone or a line an adapter refuses.
    """
    person = _user(buyer)
    priced: list[pricing.QuoteLine] = []
    for kind, key, quantity, options in lines:
        adapter = adapter_for(kind)
        item = adapter.get(str(key))
        if item is None:
            raise refuse("An item in the cart is no longer for sale.")
        chosen = adapter.clean_options(item, dict(options))
        adapter.validate(item, int(quantity), chosen, person)
        priced.append(quote_line(adapter, item, int(quantity), chosen, person))
    return priced


def quote_lines(
    lines: Sequence[tuple[str, str, int, Mapping[str, Any]]],
    *,
    email: str = "",
    billing: Mapping[str, Any] | None = None,
    shipping: Mapping[str, Any] | None = None,
    coupon: str = "",
    method: str | None = None,
) -> pricing.Quote:
    """What an order of ``lines`` would come to, as :func:`place_order` would price it.

    Staff see it before they place an order by hand: the coupon (a code; an unknown
    one is a ``coupon_problem``), the ways to send it to the address, the tax and
    the total. Nothing is written or held.

    :raises ValidationError: for no lines, or a line an adapter refuses.
    """
    if not lines:
        raise ValidationError({"lines": ["Add something to the order."]})
    person = account_for(email) if email else None
    priced = priced_lines(lines, person)
    found = pricing.find_coupon(coupon) if coupon.strip() else None
    shipped = any(line.needs_shipping for line in priced)
    address = dict(shipping or {}) if shipped and shipping else dict(billing or {})
    result = pricing.quote(
        priced,
        currency=conf.currency(),
        buyer=person,
        email=email,
        address=address,
        coupon=found,
        method=method,
    )
    if coupon.strip() and found is None:
        result.coupon_problem = "No coupon has that code."
    return result


@transaction.atomic
def place_order(
    lines: Sequence[tuple[str, str, int, Mapping[str, Any]]],
    *,
    user: Any = None,
    email: str,
    name: str = "",
    billing: Mapping[str, Any] | None = None,
    shipping: Mapping[str, Any] | None = None,
    note: str = "",
    coupon: Coupon | str | None = None,
    method: str | None = None,
    deposit: bool = False,
    hold: int | None = None,
) -> Order:
    """A pending order of ``lines`` (``(kind, key, quantity, options)``), every line held.

    The one way to create an order: :func:`checkout` calls it with a cart's
    lines, and an app calls it for an order made another way (a quote, staff
    by hand). Each line copies the item's name, SKU, options in words and
    price now. The totals come from :func:`karni_commerce.pricing.quote`: the
    coupon (a code or a :class:`Coupon`), the shipping ``method`` (an id of
    the methods offered for the address) and the tax.

    ``deposit``: the buyer pays the lines' deposits first (``Order.deposit``) and
    the rest later. ``hold`` is how many minutes the order waits for its payment
    (default ``KARNI_COMMERCE_HOLD_MINUTES``), cut short by a line's own hold
    (``Sellable.hold_minutes``). An order whose total is zero is paid at once,
    with no payment: each line is taken (``on_paid``), whatever it sells.

    :raises ValidationError: for no lines, an item that is gone, a line an
        adapter refuses or cannot hold, a coupon that cannot be used, no
        way to send the order to its address, or a deposit asked of lines that
        allow none. Nothing is held then.
    """
    if not lines:
        raise ValidationError({"cart": ["The cart is empty."]})
    if not email:
        raise ValidationError({"email": ["An email address, for the confirmation."]})
    person = _user(user)
    currency = conf.currency()
    priced = priced_lines(lines, person)
    buyer = buyer_person(
        user=person,
        email=str(email),
        name=str(name),
        phone=str((billing or {}).get("phone", "") or ""),
    )
    found = pricing.find_coupon(coupon) if isinstance(coupon, str) else coupon
    if isinstance(coupon, str) and coupon.strip() and found is None:
        raise refuse("No coupon has that code.", field="coupon")
    if found is not None:
        # One checkout at a time per coupon, so its limits hold with two buyers at once.
        found = Coupon.objects.select_for_update().get(pk=found.pk)
    shipped = any(line.needs_shipping for line in priced)
    address = dict(shipping or {}) if shipped and shipping else dict(billing or {})
    result = pricing.quote(
        priced,
        currency=currency,
        buyer=person,
        email=str(email),
        address=address,
        coupon=found,
        method=method,
    )
    if result.coupon_problem:
        raise refuse(result.coupon_problem, field="coupon")
    if result.shipping_problem:
        raise refuse(result.shipping_problem, field="shipping_method")
    if result.methods and result.method is None:
        raise refuse("Choose a way to send it.", field="shipping_method")
    if deposit and result.deposit is None:
        raise refuse("This order cannot be paid by a deposit: pay it in full.", field="pay")
    built: list[OrderLine] = []
    for position, line in enumerate(priced):
        built.append(
            OrderLine(
                kind=line.kind,
                item=line.item,
                options=dict(line.options),
                name=line.name,
                sku=line.sku,
                details=list(line.details),
                quantity=line.quantity,
                currency=currency,
                unit_price=line.unit,
                compare_at_price=line.compare_at,
                line_total=line.line_total,
                discount=line.discount,
                tax_rate=line.tax_rate,
                tax=line.tax,
                total=money(line.total),
                needs_shipping=line.needs_shipping,
                position=position,
            )
        )
    order = _save_new(
        Order(
            user=person,
            email=str(email).strip(),
            buyer_name=str(name).strip(),
            person=buyer,
            status="pending",
            currency=currency,
            subtotal=result.subtotal,
            discount_total=money(result.discount),
            shipping_total=money(result.shipping),
            tax_total=money(result.tax),
            total=result.total,
            prices_include_tax=result.prices_include_tax,
            coupon_code=result.coupon.code if result.coupon is not None else "",
            shipping_method=result.method.name if result.method is not None else "",
            tax_lines=[
                {"name": tax.name, "rate": f"{tax.rate:.4f}", "amount": f"{tax.amount:.2f}"}
                for tax in result.tax_lines
            ],
            billing=dict(billing or {}),
            shipping=dict(shipping or {}) if shipped else {},
            needs_shipping=shipped,
            note=note,
            key=new_key(),
            deposit=result.deposit if deposit and result.deposit is not None else ZERO,
            hold_until=timezone.now() + timedelta(minutes=shortest_hold(priced, hold)),
        )
    )
    for line in built:
        line.order = order
    OrderLine.objects.bulk_create(built)
    for line in sorted(built, key=lambda row: (row.kind, row.item)):  # one order: no deadlocks
        adapter_for(line.kind).hold(line)
    if result.coupon is not None:
        CouponUse.objects.create(
            coupon=result.coupon,
            order=order,
            user=person,
            email=order.email,
            currency=currency,
            amount=money(result.discount),
        )
    events.order_placed.send(sender=Order, order=order)
    if order.total <= 0:
        # Nothing to pay (a free course, a free booking, a coupon that takes it all):
        # the order is paid now, and each line is taken as a paid one is.
        _mark_paid(order)
    return order


@transaction.atomic
def checkout(
    cart: Cart,
    *,
    user: Any = None,
    email: str,
    name: str = "",
    billing: Mapping[str, Any] | None = None,
    shipping: Mapping[str, Any] | None = None,
    note: str = "",
    method: str | None = None,
    deposit: bool = False,
) -> Order:
    """Turn ``cart`` into a pending order (:func:`place_order`), and empty the cart.

    The cart's coupon goes on the order, ``method`` is the shipping method
    the buyer chose, and ``deposit`` that they pay the deposit now and the rest
    later (when every line allows one). A free order comes back paid.

    :raises ValidationError: for an empty cart, or a line that cannot be bought.
    """
    release_expired()
    rows = list(cart.lines.order_by("created_at", "pk"))
    lines = [(row.kind, row.item, row.quantity, row.options) for row in rows]
    order = place_order(
        lines,
        user=user,
        email=email,
        name=name,
        billing=billing,
        shipping=shipping,
        note=note,
        coupon=cart.coupon,
        method=method,
        deposit=deposit,
    )
    cart.lines.all().delete()
    if cart.coupon_id is not None:
        cart.coupon = None
        cart.save(update_fields=["coupon", "updated_at"])
    return order


def order_link(order: Order) -> str:
    """The order's page in the app, with the key a guest reads it by."""
    frontend = str(getattr(settings, "KARNI_FRONTEND_URL", "") or "").rstrip("/")
    path = str(conf.get("KARNI_COMMERCE_ORDER_PATH")).format(number=order.number, key=order.key)
    return f"{frontend}{path}"


def _with(url: str, **params: str) -> str:
    joiner = "&" if "?" in url else "?"
    return url + joiner + "&".join(f"{key}={value}" for key, value in params.items())


def _held_for(order: Order) -> int:
    """How many minutes ``order`` was held for when it was placed (a retry holds it as long)."""
    if order.hold_until is None or order.created_at is None:
        return hold_minutes()
    seconds = (order.hold_until - order.created_at).total_seconds()
    return max(1, round(seconds / 60))


def amount_due(order: Order) -> Decimal:
    """What the next payment of ``order`` asks: its deposit while that is due, else the
    balance (``Order.due_now``)."""
    return money(order.due_now)


def open_payment(order: Order) -> str | None:
    """Start the payment of what ``order`` owes now. Returns where the buyer pays.

    What it owes now is the deposit, while the buyer chose one and has paid
    nothing, else the balance: the whole total, or what is left of a part-paid
    order (its balance link). An order whose payment failed is held again first
    (its items may have sold since), for as long as it was held at first. An
    order with nothing to pay settles at once and returns ``None`` (a free
    order is paid when it is placed, so it answers ``None`` too).

    :raises ValidationError: when the order is not waiting for a payment, or
        its items cannot be held again.
    """
    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        if locked.status == "paid":
            return None  # a free order, paid when it was placed: nothing to pay
        if locked.status == "failed":
            for line in locked.lines.order_by("kind", "item"):
                adapter_for(line.kind).hold(line)
            locked.transition(
                "status",
                "pending",
                hold_until=timezone.now() + timedelta(minutes=_held_for(locked)),
            )
        balance = locked.status == "part_paid"
        if not balance and (
            locked.status != "pending"
            or (locked.hold_until is not None and locked.hold_until <= timezone.now())
        ):
            raise ValidationError({"order": ["This order is not waiting for a payment."]})
        due = amount_due(locked)
        if due <= 0:
            if locked.status == "pending":
                _mark_paid(locked)
            order.refresh_from_db()
            return None
        # A payment of this order still open at the provider: send the buyer back to it
        # (a second Pay, or a page reloaded), instead of starting another.
        waiting = (
            locked.payments.filter(payment__status=Payment.Status.PENDING, amount=due)
            .select_related("payment")
            .order_by("-created_at")
            .first()
        )
        if waiting is not None and (waiting.payment.metadata or {}).get("url"):
            return str(waiting.payment.metadata["url"])
        if locked.deposit_due:
            purpose = OrderPayment.Purpose.DEPOSIT
        elif balance:
            purpose = OrderPayment.Purpose.BALANCE
        elif locked.payments.exists():
            purpose = OrderPayment.Purpose.RETRY
        else:
            purpose = OrderPayment.Purpose.FULL
    back = order_link(locked)
    payment, session = create_checkout(
        locked.user,
        amount=due,
        currency=locked.currency,
        success_url=_with(back, paid="1"),
        cancel_url=back,
        metadata={"commerce_order": str(locked.pk), "number": locked.number},
    )
    OrderPayment.objects.create(
        order=locked, payment=payment, purpose=purpose, currency=locked.currency, amount=due
    )
    if session.url:
        payment.metadata = {**(payment.metadata or {}), "url": session.url}
        payment.save(update_fields=["metadata", "updated_at"])
    order.refresh_from_db()
    return session.url


# -- the settlement ------------------------------------------------------------------------


def _lines(order: Order) -> list[tuple[OrderLine, Sellable | None]]:
    known = kinds()
    rows = order.lines.order_by("kind", "item", "position")
    return [(line, known.get(line.kind)) for line in rows]


def _each(order: Order, hook: str) -> None:
    for line, adapter in _lines(order):
        if adapter is None:
            logger.warning("Order %s: no adapter sells %r any more.", order.number, line.kind)
            continue
        getattr(adapter, hook)(line)


def _mark_paid(order: Order, *, take: bool = True) -> None:
    """``order`` is paid in full: its invoice, each line taken (unless its deposit took them)."""
    order.transition("status", "paid", paid_at=timezone.now())
    issue_invoice(order)
    if take:
        _each(order, "on_paid")
    events.order_paid.send(sender=Order, order=order)


@transaction.atomic
def settle(payment: Payment) -> Order | None:
    """Move the order ``payment`` belongs to, now that the provider settled it.

    Succeeded: the money is counted, and once it covers the total the order
    is paid and each line is taken (``on_paid``). A deposit makes the order
    ``part_paid`` and takes the lines then, so the balance paid later takes
    nothing twice. Failed or cancelled: an order waiting for this payment
    fails and lets its lines go (``release``). A failed balance payment leaves
    the order part paid. Money for an order that is no longer waiting (it
    expired, or was cancelled) is refunded at once.
    """
    link = OrderPayment.objects.filter(payment=payment).first()
    if link is None:
        return None
    order = Order.objects.select_for_update().get(pk=link.order_id)
    if payment.status == Payment.Status.SUCCEEDED:
        order.amount_paid = money(Decimal(order.amount_paid) + Decimal(payment.amount))
        order.save(update_fields=["amount_paid", "updated_at"])
        if order.status not in ("pending", "part_paid"):
            reason = f"order {order.number} was {order.status} when its payment came in"
            _refund_on_commit(order, payment, reason)
            return order
        if order.amount_paid >= order.total:
            _mark_paid(order, take=order.status == "pending")
        elif order.status == "pending":
            order.transition("status", "part_paid")
            _each(order, "on_paid")  # the deposit secures the lines: the slot is the buyer's
            events.order_part_paid.send(sender=Order, order=order, amount=payment.amount)
    elif payment.status in (Payment.Status.FAILED, Payment.Status.CANCELED):
        others = order.payments.exclude(pk=link.pk).filter(payment__status=Payment.Status.PENDING)
        if order.status == "pending" and not others.exists():
            _each(order, "release")
            order.transition("status", "failed")
            events.order_failed.send(sender=Order, order=order)
    return order


def _refund_on_commit(order: Order, payment: Payment, reason: str) -> None:
    """Once this transaction commits, give back what is left of ``payment`` (no restock)."""
    order_pk, payment_pk = order.pk, payment.pk
    transaction.on_commit(lambda: _refund_payment(order_pk, payment_pk, reason))


@transaction.atomic
def _refund_payment(order_pk: Any, payment_pk: Any, reason: str) -> OrderRefund | None:
    payment = Payment.objects.get(pk=payment_pk)
    if payment.status not in (Payment.Status.SUCCEEDED, Payment.Status.PARTIALLY_REFUNDED):
        return None
    left = money(Decimal(payment.amount) - refunded_amount(payment))
    if left <= 0:
        return None
    made = create_refund(payment, left, reason=reason)
    order = Order.objects.get(pk=order_pk)
    return OrderRefund.objects.create(
        order=order, refund=made, currency=order.currency, amount=left, reason=reason[:255]
    )


@transaction.atomic
def cancel(order: Order, reason: str = "") -> Order:
    """Cancel ``order``.

    Waiting for its payment (or failed): its lines are let go (``release``).
    Paid, or part paid by its deposit: each line is undone (``on_cancelled``)
    and everything paid goes back to the buyer through the payment provider.

    :raises ValidationError: for an order that is refunded or cancelled already.
    """
    locked = Order.objects.select_for_update().get(pk=order.pk)
    if locked.status in ("pending", "failed"):
        if locked.status == "pending":
            _each(locked, "release")
    elif locked.status in ("paid", "part_paid"):
        _each(locked, "on_cancelled")
        succeeded = locked.payments.filter(payment__status=Payment.Status.SUCCEEDED)
        for link in succeeded.select_related("payment"):
            _refund_on_commit(locked, link.payment, reason or f"order {locked.number} cancelled")
    else:
        raise ValidationError(
            {"status": [f"An order that is {locked.status} cannot be cancelled."]}
        )
    locked.transition("status", "cancelled", cancelled_at=timezone.now())
    events.order_cancelled.send(sender=Order, order=locked, reason=reason)
    order.refresh_from_db()
    return locked


def release_expired(now: datetime | None = None) -> int:
    """Cancel the orders whose payment did not come in time: their items are free again."""
    moment = now or timezone.now()
    count = 0
    for order in Order.objects.filter(status="pending", hold_until__lt=moment):
        cancel(order, reason="the payment did not come in time")
        count += 1
    return count


def request_balance(order: Order) -> str:
    """Email the buyer of a part-paid order the link to pay the rest (``commerce.balance_due``).

    The same email goes out when the deposit comes in. Returns the link.

    :raises ValidationError: for an order that has no deposit paid and balance left.
    """
    found = Order.objects.get(pk=order.pk)
    if found.status != "part_paid" or found.balance <= 0:
        raise ValidationError(
            {"status": ["Only an order with its deposit paid has a balance to ask for."]}
        )
    pk = found.pk

    def ask() -> None:
        from karni_commerce import messages

        again = Order.objects.filter(pk=pk).first()
        if again is not None and again.status == "part_paid":
            messages.send("commerce.balance_due", again)

    transaction.on_commit(ask)
    return order_link(found)


# -- refunds -------------------------------------------------------------------------------


def _refund_amount(order: Order, lines: Mapping[str, int], now: datetime) -> Decimal:
    known = {str(line.pk): line for line in order.lines.all()}
    total = ZERO
    for key, quantity in lines.items():
        line = known.get(str(key))
        if line is None:
            raise refuse(f"Order {order.number} has no line {key}.", field="lines")
        if quantity < 1 or quantity > line.quantity - line.quantity_refunded:
            raise refuse(
                f"{line.name}: at most {line.quantity - line.quantity_refunded} can be refunded.",
                field="lines",
            )
        amount = money(line.unit_paid() * quantity)
        adapter = kinds().get(line.kind)
        limit = adapter.refund_limit(line, now) if adapter is not None else amount
        total += min(amount, money(limit))
    if total <= 0:
        # Each line's adapter says nothing may go back now (a booking that starts soon).
        raise refuse("Nothing of these lines can be refunded now.", field="lines")
    return total


@transaction.atomic
def refund(
    order: Order,
    *,
    amount: Decimal | None = None,
    lines: Mapping[str, int] | None = None,
    restock: bool = False,
    reason: str = "",
) -> OrderRefund:
    """Refund part or all of a paid order, by lines (``{line id: quantity}``) or by an amount.

    The refund is asked of the provider now. When it goes through
    (:func:`settle_refund`), the lines are refunded (``on_refunded``, with
    the items back when ``restock``) and the order is refunded or part
    refunded.

    :raises ValidationError: for an order that took no money, nothing to
        refund, more than was paid, or a line quantity out of range.
    """
    locked = Order.objects.select_for_update().get(pk=order.pk)
    if locked.status not in PAID_STATES:
        raise ValidationError({"status": [f"An order that is {locked.status} took no money."]})
    chosen = {str(key): int(value) for key, value in dict(lines or {}).items() if int(value)}
    if amount is None:
        if not chosen:
            raise refuse("Name the lines to refund, or an amount.", field="amount")
        amount = _refund_amount(locked, chosen, timezone.now())
    amount = money(amount)
    pending = OrderRefund.objects.filter(order=locked, settled_at__isnull=True).exclude(
        refund__status=Refund.Status.FAILED
    )
    waiting = sum((money(row.amount) for row in pending), ZERO)
    room = money(locked.refundable - waiting)
    if amount <= 0 or amount > room:
        raise refuse(f"At most {room} {locked.currency} can be refunded.", field="amount")
    link = (
        locked.payments.filter(
            payment__status__in=[Payment.Status.SUCCEEDED, Payment.Status.PARTIALLY_REFUNDED]
        )
        .select_related("payment")
        .order_by("-created_at")
        .first()
    )
    if link is None:
        raise refuse("The order has no payment to refund.", field="amount")
    made = create_refund(link.payment, amount, reason=reason or f"order {locked.number}")
    return OrderRefund.objects.create(
        order=locked,
        refund=made,
        currency=locked.currency,
        amount=amount,
        lines=chosen,
        restock=restock,
        reason=reason,
    )


@transaction.atomic
def settle_refund(refund_row: Refund) -> OrderRefund | None:
    """The provider confirmed a refund: apply it to its order, once."""
    record = (
        OrderRefund.objects.select_for_update()
        .filter(refund=refund_row, settled_at__isnull=True)
        .first()
    )
    if record is None or refund_row.status != Refund.Status.SUCCEEDED:
        return None
    order = Order.objects.select_for_update().get(pk=record.order_id)
    lines = {str(line.pk): line for line in order.lines.all()}
    known = kinds()
    for key, quantity in record.line_quantities().items():
        line = lines.get(key)
        if line is None:
            continue
        quantity = min(quantity, line.quantity - line.quantity_refunded)
        if quantity <= 0:
            continue
        line.quantity_refunded += quantity
        line.save(update_fields=["quantity_refunded", "updated_at"])
        adapter = known.get(line.kind)
        if adapter is not None:
            adapter.on_refunded(line, quantity, record.restock)
    order.amount_refunded = money(Decimal(order.amount_refunded) + Decimal(record.amount))
    order.save(update_fields=["amount_refunded", "updated_at"])
    full = order.amount_refunded >= order.amount_paid
    if order.status in PAID_STATES:
        target = "refunded" if full else "part_refunded"
        if target != order.status:
            order.transition("status", target)
    record.settled_at = timezone.now()
    record.save(update_fields=["settled_at", "updated_at"])
    events.order_refunded.send(
        sender=Order, order=order, refund=record, amount=record.amount, full=full
    )
    return record


def staff_lines(orders: Iterable[Order]) -> dict[Any, list[OrderLine]]:
    """The lines of ``orders`` in one query, by order id (for lists that show them)."""
    found: dict[Any, list[OrderLine]] = {}
    ids = [order.pk for order in orders]
    for line in OrderLine.objects.filter(order_id__in=ids).order_by("position"):
        found.setdefault(line.order_id, []).append(line)
    return found


# -- staff: notes and orders placed by hand ------------------------------------------------


@transaction.atomic
def add_note(order: Order, body: str, *, kind: str = "internal", author: Any = None) -> OrderNote:
    """A note on ``order``: ``internal`` for the staff, ``customer`` for the buyer too.

    A note to the customer is emailed to them (``commerce.order_note``) and shows
    on their order page.

    :raises ValidationError: for an empty note or an unknown kind.
    """
    text = str(body or "").strip()
    if not text:
        raise refuse("Write the note.", field="body")
    if kind not in OrderNote.Kind.values:
        raise refuse(f"A note is {' or '.join(OrderNote.Kind.values)}.", field="kind")
    note = OrderNote.objects.create(order=order, kind=kind, body=text, author=_user(author))
    events.order_note_added.send(sender=Order, order=order, note=note)
    return note


def account_for(email: str) -> Any:
    """The user whose verified email is ``email``, or ``None``: an order placed for them is
    theirs."""
    from django.contrib.auth import get_user_model

    if not email:
        return None
    found = get_user_model()._default_manager.filter(email__iexact=email.strip()).first()
    if found is None or not getattr(found, "email_verified", False):
        return None
    return found


@transaction.atomic
def place_manual_order(
    lines: Sequence[tuple[str, str, int, Mapping[str, Any]]],
    *,
    staff: Any,
    email: str,
    name: str = "",
    billing: Mapping[str, Any] | None = None,
    shipping: Mapping[str, Any] | None = None,
    note: str = "",
    send_link: bool = True,
    coupon: str = "",
    method: str | None = None,
    deposit: bool = False,
) -> Order:
    """An order staff place for a buyer (a phone order), waiting for the buyer's payment.

    The lines are priced and held as at checkout (:func:`place_order`), for
    ``KARNI_COMMERCE_MANUAL_HOLD_MINUTES`` (or a line's shorter hold), and
    ``deposit`` asks for the deposit first. The order belongs to the account
    whose verified email is ``email``, when there is one. An internal note says
    who placed it, and with ``send_link`` the buyer gets the link to pay
    (``commerce.payment_request``). A free order is paid at once, and the buyer
    gets the confirmation instead.

    :raises ValidationError: as :func:`place_order` does.
    """
    order = place_order(
        lines,
        user=account_for(email),
        email=email,
        name=name,
        billing=billing,
        shipping=shipping,
        note=note,
        coupon=coupon or None,
        method=method,
        deposit=deposit,
        hold=int(conf.get("KARNI_COMMERCE_MANUAL_HOLD_MINUTES")),
    )
    who = getattr(staff, "get_full_name", lambda: "")() or getattr(staff, "email", "") or "staff"
    add_note(order, f"Placed by hand by {who}.", author=staff)
    if send_link and order.status == "pending":
        pk = order.pk

        def ask_for_payment() -> None:
            from karni_commerce import messages

            found = Order.objects.filter(pk=pk).first()
            if found is not None:
                messages.send("commerce.payment_request", found)

        transaction.on_commit(ask_for_payment)
    return order


# -- invoices --------------------------------------------------------------------------------


def next_invoice_number() -> int:
    """One more than the highest invoice number, from ``KARNI_COMMERCE_FIRST_INVOICE``."""
    highest = Invoice.objects.without("soft_delete", reason="numbers are never reused").aggregate(
        highest=models.Max("number")
    )["highest"]
    return max(int(highest or 0) + 1, int(conf.get("KARNI_COMMERCE_FIRST_INVOICE")))


def seller() -> dict[str, str]:
    """The business's details an invoice prints, as they are now (preferences)."""
    found = preferences.details()
    return {
        "name": found.legal_name or found.name,
        "trading_name": found.name,
        "address": found.address,
        "phone": found.phone,
        "email": found.email,
        "tax_number": found.tax_number,
    }


def issue_invoice(order: Order) -> Invoice:
    """The invoice of ``order``, numbered the first time it is asked for (once paid).

    The number counts up with no gap from ``KARNI_COMMERCE_FIRST_INVOICE``, and
    the reference carries the ``commerce.invoice_prefix`` of that day.
    """
    found = Invoice.objects.filter(order=order).first()
    if found is not None:
        return found
    prefix = preferences.value("commerce.invoice_prefix", "INV-")
    for _attempt in range(5):
        number = next_invoice_number()
        try:
            with transaction.atomic():
                made = Invoice.objects.create(
                    order=order,
                    number=number,
                    reference=f"{prefix}{number}",
                    issued_at=order.paid_at or timezone.now(),
                    seller=seller(),
                )
        except IntegrityError:
            continue  # another order took the number at the same moment
        publish(
            "commerce.invoice.issued",
            subject=made,
            person=order.person_id,
            invoice=str(made.pk),
            order=str(order.pk),
            number=made.reference,
        )
        return made
    raise ValidationError({"invoice": ["Too many invoices at once. Try again."]})


def staff_emails() -> list[str]:
    """Who gets the staff's emails: the Checkout settings' list, else the project's."""
    typed = preferences.value("commerce.staff_emails", "")
    found = [part.strip() for part in typed.replace(";", ",").split(",") if part.strip()]
    return found or [str(address) for address in conf.get("KARNI_COMMERCE_STAFF_EMAILS") or []]


# -- abandoned carts -------------------------------------------------------------------------


def abandoned_carts(now: datetime | None = None) -> models.QuerySet[Cart]:
    """Carts with lines that nobody touched for ``commerce.abandoned_after_hours``.

    Each with ``line_count`` and ``item_count``. A cart that checked out has no lines
    left, so it is never here.
    """
    hours = preferences.value("commerce.abandoned_after_hours", 1)
    before = (now or timezone.now()) - timedelta(hours=max(int(hours), 1))
    live = models.Q(lines__deleted_at__isnull=True)
    return (
        Cart.objects.filter(touched_at__lt=before)
        .annotate(
            line_count=models.Count("lines", filter=live),
            item_count=models.Sum("lines__quantity", filter=live),
        )
        .filter(line_count__gt=0)
        .select_related("user", "coupon")
        .order_by("-touched_at")
    )


def cart_value(cart: Cart) -> Decimal:
    """What the lines of ``cart`` come to now, priced by their adapters."""
    return money(sum((row.line_total for row in cart_lines(cart)), ZERO))


def abandoned_rows(carts: list[Cart]) -> list[dict[str, Any]]:
    """The abandoned ``carts`` as the staff list shows them, priced together: one query
    for their lines and one per kind for the items, however many carts."""
    lines = list(CartLine.objects.filter(cart__in=carts).order_by("created_at", "pk"))
    known = kinds()
    items: dict[tuple[str, str], Any] = {}
    by_kind: dict[str, set[str]] = {}
    for line in lines:
        by_kind.setdefault(line.kind, set()).add(line.item)
    for kind, keys in by_kind.items():
        adapter = known.get(kind)
        if adapter is not None:
            for key, item in adapter.get_many(keys).items():
                items[(kind, key)] = item
    rows: dict[Any, dict[str, Any]] = {
        cart.pk: {
            "id": str(cart.pk),
            "email": (cart.user.email if cart.user is not None else "") or cart.email,
            "name": cart.user.get_full_name() if cart.user is not None else "",
            "signed_in": cart.user_id is not None,
            "items": 0,
            "lines": [],
            "value": ZERO,
            "currency": conf.currency().upper(),
            "coupon": cart.coupon.code if cart.coupon is not None else None,
            "touched_at": cart.touched_at,
            "created_at": cart.created_at,
        }
        for cart in carts
    }
    for line in lines:
        row = rows[line.cart_id]
        adapter = known.get(line.kind)
        item = items.get((line.kind, line.item))
        row["items"] += line.quantity
        if adapter is None or item is None:
            row["lines"].append(f"{line.quantity} x (no longer for sale)")
            continue
        row["lines"].append(f"{line.quantity} x {adapter.name(item, line.options)}")
        price = adapter.price(item, line.options, None)
        row["value"] += money(price.unit) * line.quantity
    for row in rows.values():
        row["value"] = f"{money(row['value']):.2f}"
    return [rows[cart.pk] for cart in carts]
