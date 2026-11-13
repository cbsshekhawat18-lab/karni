"""Experimental. The emails commerce sends, each under a stable kind name.

* ``commerce.order_paid``, to the buyer: the order is paid (the confirmation).
* ``commerce.new_order``, to the addresses in ``KARNI_COMMERCE_STAFF_EMAILS``:
  an order is paid and waits to be fulfilled.
* ``commerce.order_cancelled``, to the buyer: the order was cancelled.
* ``commerce.order_refunded``, to the buyer: a refund went through.
* ``commerce.order_note``, to the buyer: staff wrote a note to the customer.
* ``commerce.payment_request``, to the buyer: staff placed an order for them
  (a phone order) and ask for its payment, with the link to pay.

An order waiting for its payment sends nothing: most never-paid orders are
a person who changed their mind.

Each renders ``karni_commerce/email/<name>_subject.txt``, ``_body.txt`` and
``_body.html`` (:func:`karni.mail.send_templated`) with ``order``,
``lines`` and ``link`` (the order's page). Listeners send them after the
order's change commits (:mod:`karni_commerce.listeners`).

Override / escape hatch: put a template of the same name earlier in
``TEMPLATES`` ``DIRS`` to change a message, switch a kind off with
``KARNI_MAIL_DISABLED_KINDS = ["commerce.new_order"]``, or call
:func:`send` with your own context.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from karni.mail import register_kind, send_templated

from karni_commerce import preferences_seam as preferences
from karni_commerce.models import Order

__all__ = ["KINDS", "ORDER_FIELDS", "business", "send"]

#: Each kind's template stem and who receives it: ``buyer`` or ``staff``.
KINDS: dict[str, tuple[str, str]] = {
    "commerce.order_paid": ("karni_commerce/email/order_paid", "buyer"),
    "commerce.new_order": ("karni_commerce/email/new_order", "staff"),
    "commerce.order_cancelled": ("karni_commerce/email/order_cancelled", "buyer"),
    "commerce.order_refunded": ("karni_commerce/email/order_refunded", "buyer"),
    "commerce.order_note": ("karni_commerce/email/order_note", "buyer"),
    "commerce.payment_request": ("karni_commerce/email/payment_request", "buyer"),
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
}

for _name, (_title, _audience, _describe, _more) in _DECLARED.items():
    register_kind(
        _name,
        title=_title,
        template=KINDS[_name][0],
        audience=_audience,
        describe=_describe,
        fields={**ORDER_FIELDS, **_more},
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


def send(kind: str, order: Order, context: Mapping[str, Any] | None = None) -> int:
    """Experimental. Send the email of ``kind`` about ``order``. Returns how many went out."""
    from karni_commerce.services import order_link

    template, audience = KINDS[kind]
    values = {
        "business": business(),
        "order": order,
        "lines": list(order.lines.all()),
        "link": order_link(order),
        **dict(context or {}),
    }
    return send_templated(template, to=_recipients(order, audience), context=values, kind=kind)
