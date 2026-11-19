"""Experimental. The emails commerce sends, each under a stable kind name.

* ``commerce.order_paid``, to the buyer: the order is paid (the confirmation).
* ``commerce.new_order``, to the addresses in ``KARNI_COMMERCE_STAFF_EMAILS``:
  an order is paid (or its deposit is) and waits to be fulfilled.
* ``commerce.order_cancelled``, to the buyer: the order was cancelled.
* ``commerce.order_refunded``, to the buyer: a refund went through.
* ``commerce.order_note``, to the buyer: staff wrote a note to the customer.
* ``commerce.payment_request``, to the buyer: staff placed an order for them
  (a phone order) and ask for its payment, with the link to pay.
* ``commerce.balance_due``, to the buyer: the deposit is paid, with what is
  left and the link to pay it (again when staff send the balance link).

An order waiting for its payment sends nothing: most never-paid orders are
a person who changed their mind.

Each kind goes to the email and, while ``karni.notify`` is installed, to the
recipient's inbox in the app (:data:`CHANNELS`): every one is about an order
of the recipient's own or one the staff fulfil, so an account holder finds it
where the order is. The inbox entry reaches the account that verified the
buyer's (or the staff's) address, never an account that only typed it.

Each renders ``karni_commerce/email/<name>_subject.txt``, ``_body.txt`` and
``_body.html`` (:func:`karni.mail.send_templated`) with ``order``,
``lines`` and ``link`` (the order's page). Listeners send them after the
order's change commits (:mod:`karni_commerce.listeners`).

Override / escape hatch: put a template of the same name earlier in
``TEMPLATES`` ``DIRS`` to change a message, switch a kind off with
``KARNI_MAIL_DISABLED_KINDS = ["commerce.new_order"]``, call
:func:`send` with your own context, keep the inbox out project-wide
(``KARNI_NOTIFY_CHANNELS = ["email"]``), or declare a kind again in your own
``messages.py`` with other ``channels=``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from karni import preferences
from karni.mail import register_kind, send_templated

from karni_commerce import conf
from karni_commerce.models import Order, OrderNote, OrderRefund

__all__ = [
    "CHANNELS",
    "KINDS",
    "ORDER_FIELDS",
    "ORDER_SAMPLES",
    "business",
    "context",
    "latest",
    "send",
]

#: Each kind's template stem and who receives it: ``buyer`` or ``staff``.
KINDS: dict[str, tuple[str, str]] = {
    "commerce.order_paid": ("karni_commerce/email/order_paid", "buyer"),
    "commerce.new_order": ("karni_commerce/email/new_order", "staff"),
    "commerce.order_cancelled": ("karni_commerce/email/order_cancelled", "buyer"),
    "commerce.order_refunded": ("karni_commerce/email/order_refunded", "buyer"),
    "commerce.order_note": ("karni_commerce/email/order_note", "buyer"),
    "commerce.payment_request": ("karni_commerce/email/payment_request", "buyer"),
    "commerce.balance_due": ("karni_commerce/email/balance_due", "buyer"),
}

_BOTH: tuple[str, ...] = ("email", "inbox")

#: Where each kind goes (``karni.mail.register_kind(channels=...)``): the email, and the
#: inbox of the recipient's account (``karni.notify``). The buyer's confirmation and the
#: balance to pay are what they look for in the app, the staff's new order is their work,
#: and a cancel, a refund, a note or a payment asked is about the buyer's own order.
CHANNELS: dict[str, tuple[str, ...]] = {
    "commerce.order_paid": _BOTH,
    "commerce.new_order": _BOTH,
    "commerce.order_cancelled": _BOTH,
    "commerce.order_refunded": _BOTH,
    "commerce.order_note": _BOTH,
    "commerce.payment_request": _BOTH,
    "commerce.balance_due": _BOTH,
}


#: What an edited order email may use (karni.mail merge fields), and what each means.
ORDER_FIELDS: dict[str, str] = {
    "business.name": "The business's name (Settings, Details)",
    "business.email": "The business's contact email",
    "business.phone": "The business's phone number",
    "order.number": "The order's number",
    "order.buyer_name": "The buyer's name (may be blank)",
    "order.email": "The buyer's email",
    "order.currency": "The currency code (EUR)",
    "order.subtotal": "What the items come to",
    "order.discount_total": "What the coupon took off",
    "order.coupon_code": "The coupon's code (may be blank)",
    "order.shipping_method": "The way it is sent (may be blank)",
    "order.shipping_total": "What sending it costs",
    "order.tax_lines.name": "Each tax line's name",
    "order.tax_lines.amount": "Each tax line's amount",
    "order.prices_include_tax": "Whether the prices include the tax",
    "order.total": "What the order comes to",
    "order.amount_paid": "What the buyer paid so far",
    "order.balance": "What is still to pay (0 once it is paid)",
    "order.status": "The order's money state: pending, paid, part_paid (its deposit paid), ...",
    "order.note": "The buyer's note (may be blank)",
    "order.hold_until": "Until when the items are kept for the payment",
    "lines.quantity": "Each line's quantity",
    "lines.name": "Each line's name, with its options",
    "lines.sku": "Each line's SKU",
    "lines.line_total": "Each line's price times its quantity",
    "link": "The order's page",
}

_DECLARED: dict[str, tuple[str, str, str, dict[str, str]]] = {
    "commerce.order_paid": (
        "Order confirmed",
        "the buyer",
        "The order is paid: the confirmation, with what they bought.",
        {},
    ),
    "commerce.new_order": (
        "New order",
        "the staff (Settings, Checkout)",
        "An order is paid and waits to be fulfilled.",
        {},
    ),
    "commerce.order_cancelled": (
        "Order cancelled",
        "the buyer",
        "The order was cancelled. A paid one's money goes back.",
        {},
    ),
    "commerce.order_refunded": (
        "Refund sent",
        "the buyer",
        "A refund of some or all of the order went through.",
        {"refund.amount": "What was refunded"},
    ),
    "commerce.order_note": (
        "A note about the order",
        "the buyer",
        "Staff wrote the buyer a note on their order.",
        {"note.body": "The note"},
    ),
    "commerce.payment_request": (
        "Pay for your order",
        "the buyer",
        "Staff placed an order for the buyer: the link to pay it.",
        {},
    ),
    "commerce.balance_due": (
        "Balance to pay",
        "the buyer",
        "The deposit is paid: what is left and the link to pay it. Sent when the deposit "
        "comes in, and when staff send the balance link.",
        {"order.deposit": "The deposit asked first"},
    ),
}

#: What a preview shows before the first order exists: an order of two lines.
ORDER_SAMPLES: dict[str, Any] = {
    "order": {
        "number": 1001,
        "buyer_name": "Sam Taylor",
        "email": "sam@example.com",
        "currency": conf.currency(),
        "subtotal": "40.00",
        "discount_total": "0.00",
        "coupon_code": "",
        "shipping_method": "Standard",
        "shipping_total": "5.00",
        "tax_lines": [{"name": "Tax", "amount": "4.50"}],
        "prices_include_tax": False,
        "total": "49.50",
        "amount_paid": "49.50",
        "balance": "0.00",
        "deposit": "0.00",
        "status": "paid",
        "note": "",
        "hold_until": "",
    },
    "lines": [
        {"quantity": 2, "name": "Linen apron", "sku": "APR-1", "line_total": "30.00"},
        {"quantity": 1, "name": "Garden twine", "sku": "TWN-1", "line_total": "10.00"},
    ],
    "link": "/orders/1001",
    "refund": {"amount": "10.00"},
    "note": {"body": "Your parcel goes out on Monday."},
}

_PAID = ("paid", "part_paid", "part_refunded", "refunded")


def _paid() -> Any:
    return Order.objects.filter(status__in=_PAID, paid_at__isnull=False).order_by("-paid_at")


def _refunded() -> tuple[Order, dict[str, Any]] | None:
    found = OrderRefund.objects.select_related("order").order_by("-created_at").first()
    return (found.order, {"refund": found}) if found is not None else None


def _noted() -> tuple[Order, dict[str, Any]] | None:
    found = (
        OrderNote.objects.filter(kind=OrderNote.Kind.CUSTOMER)
        .select_related("order")
        .order_by("-created_at")
        .first()
    )
    return (found.order, {"note": found}) if found is not None else None


def _order(rows: Callable[[], Any]) -> Callable[[], tuple[Order, dict[str, Any]] | None]:
    def first() -> tuple[Order, dict[str, Any]] | None:
        found = rows().first()
        return (found, {}) if found is not None else None

    return first


#: How each email finds the latest record it would be sent about, for its preview.
_LATEST: dict[str, Callable[[], tuple[Order, dict[str, Any]] | None]] = {
    "commerce.order_paid": _order(_paid),
    "commerce.new_order": _order(_paid),
    "commerce.order_cancelled": _order(
        lambda: Order.objects.filter(status="cancelled").order_by("-updated_at")
    ),
    "commerce.order_refunded": _refunded,
    "commerce.order_note": _noted,
    "commerce.payment_request": _order(
        lambda: Order.objects.filter(status="pending").order_by("-created_at")
    ),
    "commerce.balance_due": _order(
        lambda: Order.objects.filter(status="part_paid").order_by("-updated_at")
    ),
}


def latest(kind: str) -> Callable[[], dict[str, Any] | None]:
    """Experimental. The context ``kind`` would be sent with, for the latest matching order
    (``None`` while there is none): what the email editor's preview shows."""

    def sample() -> dict[str, Any] | None:
        found = _LATEST[kind]()
        return context(found[0], found[1]) if found is not None else None

    return sample


for _name, (_title, _audience, _describe, _more) in _DECLARED.items():
    register_kind(
        _name,
        title=_title,
        template=KINDS[_name][0],
        audience=_audience,
        describe=_describe,
        fields={**ORDER_FIELDS, **_more},
        sample=latest(_name),
        samples=ORDER_SAMPLES,
        channels=CHANNELS[_name],
    )


def business() -> dict[str, str]:
    """The business's details an email may show (Settings, Details)."""
    found = preferences.details()
    return {"name": found.name, "email": found.email, "phone": found.phone}


def _recipients(order: Order, audience: str) -> list[str]:
    if audience == "staff":
        from karni_commerce.services import staff_emails

        return staff_emails()
    return [order.email]


def context(order: Order, more: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Experimental. What an order's email renders with: the business, the order, its
    lines, its page, and ``more`` (the refund, the note)."""
    from karni_commerce.services import order_link

    return {
        "business": business(),
        "order": order,
        "lines": list(order.lines.all()),
        "link": order_link(order),
        **dict(more or {}),
    }


def send(kind: str, order: Order, more: Mapping[str, Any] | None = None) -> int:
    """Experimental. Send the email of ``kind`` about ``order``. Returns how many went out."""
    template, audience = KINDS[kind]
    values = context(order, more)
    return send_templated(template, to=_recipients(order, audience), context=values, kind=kind)
