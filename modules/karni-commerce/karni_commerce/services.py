"""Experimental. The order path: the cart, checkout, the settlement, cancelling and refunds.

Every change goes through these functions, each in one transaction, and
every price and total is computed here from the sellable adapters
(:mod:`karni_commerce.sellables`), never taken from the client.

* :func:`set_line` puts an item in a cart, after the adapter's ``validate``.
* :func:`checkout` turns a cart into a pending :class:`Order`: each line's
  name, SKU and price are copied, every line is held (``Sellable.hold``) or
  none is, and the order holds them for ``KARNI_COMMERCE_HOLD_MINUTES``.
* :func:`open_payment` starts the payment at the provider for what is due.
  A total of zero settles at once, with no payment.
* :func:`settle` moves the order when karni-payments reports its payment
  (:mod:`karni_commerce.listeners`): paid (``Sellable.on_paid``), or failed
  (``Sellable.release``). Money that arrives for an order that stopped
  waiting goes back at once.
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
from karni_payments.models import Payment, Refund
from karni_payments.services import create_checkout, create_refund, refunded_amount
from rest_framework.exceptions import ValidationError

from karni_commerce import conf, events
from karni_commerce.models import (
    ZERO,
    Cart,
    CartLine,
    Order,
    OrderLine,
    OrderNote,
    OrderPayment,
    OrderRefund,
    new_key,
)
from karni_commerce.sellables import Price, Sellable, adapter_for, kinds, refuse

__all__ = [
    "PricedLine",
    "add_note",
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

    :raises ValidationError: for an unknown kind or item, more than
        ``KARNI_COMMERCE_MAX_QUANTITY``, or a line the adapter refuses.
    """
    adapter = adapter_for(kind)
    item = adapter.get(str(key))
    if item is None:
        raise refuse("Nothing like that is for sale here.")
    current = CartLine.objects.filter(cart=cart, kind=kind, item=adapter.key(item)).first()
    wanted = int(quantity) + (current.quantity if add and current is not None else 0)
    if wanted <= 0:
        if current is not None:
            current.delete()
        return None
    if wanted > max_quantity():
        raise refuse(f"At most {max_quantity()} of one item.", field="quantity")
    chosen = dict(options or {})
    adapter.validate(item, wanted, chosen, _user(buyer))
    if current is None:
        return CartLine.objects.create(
            cart=cart, kind=kind, item=adapter.key(item), quantity=wanted, options=chosen
        )
    current.quantity = wanted
    current.options = chosen or current.options
    current.save(update_fields=["quantity", "options", "updated_at"])
    return current


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


def hold_minutes() -> int:
    return int(conf.get("KARNI_COMMERCE_HOLD_MINUTES"))


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
) -> Order:
    """A pending order of ``lines`` (``(kind, key, quantity, options)``), every line held.

    The one way to create an order: :func:`checkout` calls it with a cart's
    lines, and an app calls it for an order made another way (a quote, staff
    by hand). Each line copies the item's name, SKU and price now. The totals
    are the sum of the lines.

    :raises ValidationError: for no lines, an item that is gone, or a line an
        adapter refuses or cannot hold. Nothing is held then.
    """
    if not lines:
        raise ValidationError({"cart": ["The cart is empty."]})
    if not email:
        raise ValidationError({"email": ["An email address, for the confirmation."]})
    person = _user(user)
    currency = conf.currency()
    built: list[OrderLine] = []
    for position, (kind, key, quantity, options) in enumerate(lines):
        adapter = adapter_for(kind)
        item = adapter.get(str(key))
        if item is None:
            raise refuse("An item in the cart is no longer for sale.")
        adapter.validate(item, int(quantity), options, person)
        price = adapter.price(item, options, person)
        unit = money(price.unit)
        built.append(
            OrderLine(
                kind=kind,
                item=adapter.key(item),
                options=dict(options),
                name=adapter.name(item, options)[:200],
                sku=adapter.sku(item, options)[:64],
                quantity=int(quantity),
                currency=currency,
                unit_price=unit,
                compare_at_price=money(price.compare_at) if price.compare_at else None,
                line_total=money(unit * int(quantity)),
                needs_shipping=adapter.needs_shipping(item, options),
                position=position,
            )
        )
    subtotal = sum((line.line_total for line in built), ZERO)
    shipped = any(line.needs_shipping for line in built)
    order = _save_new(
        Order(
            user=person,
            email=str(email).strip(),
            buyer_name=str(name).strip(),
            status="pending",
            currency=currency,
            subtotal=subtotal,
            total=subtotal,
            billing=dict(billing or {}),
            shipping=dict(shipping or {}) if shipped else {},
            needs_shipping=shipped,
            note=note,
            key=new_key(),
            hold_until=timezone.now() + timedelta(minutes=hold_minutes()),
        )
    )
    for line in built:
        line.order = order
    OrderLine.objects.bulk_create(built)
    for line in sorted(built, key=lambda row: (row.kind, row.item)):  # one order: no deadlocks
        adapter_for(line.kind).hold(line)
    events.order_placed.send(sender=Order, order=order)
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
) -> Order:
    """Turn ``cart`` into a pending order (:func:`place_order`), and empty the cart.

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
    )
    cart.lines.all().delete()
    return order


def order_link(order: Order) -> str:
    """The order's page in the app, with the key a guest reads it by."""
    frontend = str(getattr(settings, "KARNI_FRONTEND_URL", "") or "").rstrip("/")
    path = str(conf.get("KARNI_COMMERCE_ORDER_PATH")).format(number=order.number, key=order.key)
    return f"{frontend}{path}"


def _with(url: str, **params: str) -> str:
    joiner = "&" if "?" in url else "?"
    return url + joiner + "&".join(f"{key}={value}" for key, value in params.items())


def open_payment(order: Order) -> str | None:
    """Start the payment of what ``order`` still owes. Returns where the buyer pays.

    An order whose payment failed is held again first (its items may have
    sold since). A total of zero settles the order at once and returns
    ``None``: nothing to pay.

    :raises ValidationError: when the order is not waiting for a payment, or
        its items cannot be held again.
    """
    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        if locked.status == "failed":
            for line in locked.lines.order_by("kind", "item"):
                adapter_for(line.kind).hold(line)
            locked.transition(
                "status",
                "pending",
                hold_until=timezone.now() + timedelta(minutes=hold_minutes()),
            )
        if locked.status != "pending" or (
            locked.hold_until is not None and locked.hold_until <= timezone.now()
        ):
            raise ValidationError({"order": ["This order is not waiting for a payment."]})
        due = locked.balance
        if due <= 0:
            _mark_paid(locked)
            order.refresh_from_db()
            return None
        purpose = (
            OrderPayment.Purpose.RETRY if locked.payments.exists() else OrderPayment.Purpose.FULL
        )
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


def _mark_paid(order: Order) -> None:
    order.transition("status", "paid", paid_at=timezone.now())
    _each(order, "on_paid")
    events.order_paid.send(sender=Order, order=order)


@transaction.atomic
def settle(payment: Payment) -> Order | None:
    """Move the order ``payment`` belongs to, now that the provider settled it.

    Succeeded: the money is counted, and once it covers the total the order
    is paid and each line is taken (``on_paid``). Failed or cancelled: an
    order waiting for this payment fails and lets its lines go (``release``).
    Money for an order that is no longer waiting (it expired, or was
    cancelled) is refunded at once.
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
            _mark_paid(order)
        elif order.status == "pending":
            order.transition("status", "part_paid")
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
    Paid: each line is undone (``on_cancelled``) and everything paid goes
    back to the buyer through the payment provider.

    :raises ValidationError: for an order that is refunded or cancelled already.
    """
    locked = Order.objects.select_for_update().get(pk=order.pk)
    if locked.status in ("pending", "failed"):
        if locked.status == "pending":
            _each(locked, "release")
    elif locked.status in ("paid",):
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
        amount = money(Decimal(line.unit_price) * quantity)
        adapter = kinds().get(line.kind)
        limit = adapter.refund_limit(line, now) if adapter is not None else amount
        total += min(amount, money(limit))
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
) -> Order:
    """An order staff place for a buyer (a phone order), waiting for the buyer's payment.

    The lines are priced and held as at checkout (:func:`place_order`), for
    ``KARNI_COMMERCE_MANUAL_HOLD_MINUTES``. The order belongs to the account
    whose verified email is ``email``, when there is one. An internal note says
    who placed it, and with ``send_link`` the buyer gets the link to pay
    (``commerce.payment_request``).

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
    )
    minutes = int(conf.get("KARNI_COMMERCE_MANUAL_HOLD_MINUTES"))
    order.hold_until = timezone.now() + timedelta(minutes=minutes)
    order.save(update_fields=["hold_until", "updated_at"])
    who = getattr(staff, "get_full_name", lambda: "")() or getattr(staff, "email", "") or "staff"
    add_note(order, f"Placed by hand by {who}.", author=staff)
    if send_link:
        pk = order.pk

        def ask_for_payment() -> None:
            from karni_commerce import messages

            found = Order.objects.filter(pk=pk).first()
            if found is not None:
                messages.send("commerce.payment_request", found)

        transaction.on_commit(ask_for_payment)
    return order
