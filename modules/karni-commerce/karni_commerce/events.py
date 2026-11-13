"""Experimental. What happens to a cart or an order, as signals any app can receive.

An app reacts to an order without importing the app that sold it::

    from django.dispatch import receiver
    from karni_commerce.events import order_paid


    @receiver(order_paid)
    def thank_the_buyer(sender, order, **kwargs):
        ...

Each signal is sent inside the transaction that made the change, so a
receiver that raises undoes it. Work that should wait for the commit (an
email, a call to another system) goes in ``transaction.on_commit``.
:data:`EVENTS` names each signal as the family events do
(``commerce.order.paid``).

The family events (:mod:`karni.events`) are declared here too, and
:mod:`karni_commerce.listeners` publishes them from these signals, in the same
transaction: another part subscribes by name and never imports commerce::

    from karni.events import Event, subscribe


    @subscribe("commerce.order.paid", version=1)
    def welcome_the_buyer(event: Event) -> None:
        ...  # event["order"], event["number"], event["total"], event.person

=============================  =====================================================
Event                          Declared fields
=============================  =====================================================
``commerce.order.placed``      order, number, total, currency, lines
``commerce.order.paid``        order, number, total, currency, paid_at, lines
``commerce.order.part_paid``   order, number, amount_paid, balance, currency
``commerce.order.cancelled``   order, number, reason
``commerce.order.refunded``    order, number, refund, amount, currency, lines, full
``commerce.invoice.issued``    invoice, order, number
=============================  =====================================================

``lines`` is a list of ``{line, kind, item, quantity, line_total}`` (a refund's:
``{line, kind, item, quantity}``, the quantities refunded). Amounts are decimal
strings. The person is the order's buyer (``Order.person``). Every order event
but the invoice's names a timeline title, so with ``karni.timeline`` installed
each one is an entry on the buyer's timeline and the order's.

Override / escape hatch: these are plain :class:`django.dispatch.Signal`
objects. A project that settles orders its own way sends them itself, and the
family events follow.
"""

from __future__ import annotations

from django.dispatch import Signal
from karni.events import declare

__all__ = [
    "EVENTS",
    "FAMILY_EVENTS",
    "cart_merged",
    "order_cancelled",
    "order_failed",
    "order_note_added",
    "order_paid",
    "order_part_paid",
    "order_placed",
    "order_refunded",
    "orders_claimed",
]

#: Checkout created the order, which waits for its payment: ``order``.
order_placed = Signal()
#: The order is paid in full: ``order``.
order_paid = Signal()
#: A part of the order is paid (a deposit): ``order``, ``amount``.
order_part_paid = Signal()
#: The order's payment did not go through: ``order``.
order_failed = Signal()
#: The order was cancelled, before its payment or by staff: ``order``, ``reason``.
order_cancelled = Signal()
#: A refund of the order went through: ``order``, ``refund`` (an OrderRefund), ``amount``,
#: ``full`` (True when everything paid went back).
order_refunded = Signal()
#: Staff wrote a note on the order: ``order``, ``note`` (an OrderNote; ``note.kind`` is
#: ``internal`` or ``customer``).
order_note_added = Signal()
#: A visitor's cart joined the cart of the person who signed in: ``cart``, ``user``.
cart_merged = Signal()
#: A person who signed in with a verified email got the orders placed as a guest with it:
#: ``user``, ``orders``.
orders_claimed = Signal()

#: The family event name of each signal (FAMILY events, version 1).
EVENTS: dict[str, Signal] = {
    "commerce.order.placed": order_placed,
    "commerce.order.paid": order_paid,
    "commerce.order.part_paid": order_part_paid,
    "commerce.order.failed": order_failed,
    "commerce.order.cancelled": order_cancelled,
    "commerce.order.refunded": order_refunded,
}

_LINES = "the lines: [{line, kind, item, quantity, line_total}]"
_ORDER = "the order's id"
_NUMBER = "the order's number"

declare(
    "commerce.order.placed",
    version=1,
    fields={
        "order": _ORDER,
        "number": _NUMBER,
        "total": "what the order comes to, a decimal string",
        "currency": "the ISO 4217 code",
        "lines": _LINES,
    },
    timeline={"title": "Order {number} placed", "body": "{total} {currency}"},
    describe="Checkout or staff placed an order. It waits for its payment.",
)
declare(
    "commerce.order.paid",
    version=1,
    fields={
        "order": _ORDER,
        "number": _NUMBER,
        "total": "what the order comes to, a decimal string",
        "currency": "the ISO 4217 code",
        "paid_at": "when it was paid in full",
        "lines": _LINES,
    },
    timeline={"title": "Order {number} paid", "body": "{total} {currency}"},
    describe="An order is paid in full.",
)
declare(
    "commerce.order.part_paid",
    version=1,
    fields={
        "order": _ORDER,
        "number": _NUMBER,
        "amount_paid": "what was paid so far, a decimal string",
        "balance": "what is still to pay, a decimal string",
        "currency": "the ISO 4217 code",
    },
    timeline={
        "title": "Deposit paid on order {number}",
        "body": "{amount_paid} {currency} paid, {balance} {currency} to pay",
    },
    describe="Part of an order is paid (a deposit). The balance is paid later.",
)
declare(
    "commerce.order.cancelled",
    version=1,
    fields={"order": _ORDER, "number": _NUMBER, "reason": "why, in words (may be blank)"},
    timeline={"title": "Order {number} cancelled", "body": "{reason}"},
    describe="An order was cancelled: before its payment, by staff, or not paid in time.",
)
declare(
    "commerce.order.refunded",
    version=1,
    fields={
        "order": _ORDER,
        "number": _NUMBER,
        "refund": "the order refund's id",
        "amount": "what went back, a decimal string",
        "currency": "the ISO 4217 code",
        "lines": "the lines refunded: [{line, kind, item, quantity}]",
        "full": "whether everything paid went back",
    },
    timeline={"title": "Refund on order {number}", "body": "{amount} {currency}"},
    describe="A refund of some or all of an order went through.",
)
declare(
    "commerce.invoice.issued",
    version=1,
    fields={"invoice": "the invoice's id", "order": _ORDER, "number": "the invoice's reference"},
    describe="A paid order got its invoice number.",
)

#: The family events commerce publishes (karni.events), by name.
FAMILY_EVENTS: tuple[str, ...] = (
    "commerce.order.placed",
    "commerce.order.paid",
    "commerce.order.part_paid",
    "commerce.order.cancelled",
    "commerce.order.refunded",
    "commerce.invoice.issued",
)
