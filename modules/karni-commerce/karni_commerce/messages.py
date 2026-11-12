"""Experimental. The emails commerce sends, each under a stable kind name.

* ``commerce.order_paid``, to the buyer: the order is paid (the confirmation).
* ``commerce.new_order``, to the addresses in ``KARNI_COMMERCE_STAFF_EMAILS``:
  an order is paid and waits to be fulfilled.
* ``commerce.order_cancelled``, to the buyer: the order was cancelled.
* ``commerce.order_refunded``, to the buyer: a refund went through.

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

from karni.mail import send_templated

from karni_commerce import conf
from karni_commerce.models import Order

__all__ = ["KINDS", "send"]

#: Each kind's template stem and who receives it: ``buyer`` or ``staff``.
KINDS: dict[str, tuple[str, str]] = {
    "commerce.order_paid": ("karni_commerce/email/order_paid", "buyer"),
    "commerce.new_order": ("karni_commerce/email/new_order", "staff"),
    "commerce.order_cancelled": ("karni_commerce/email/order_cancelled", "buyer"),
    "commerce.order_refunded": ("karni_commerce/email/order_refunded", "buyer"),
}


def _recipients(order: Order, audience: str) -> list[str]:
    if audience == "staff":
        return [str(address) for address in conf.get("KARNI_COMMERCE_STAFF_EMAILS") or []]
    return [order.email]


def send(kind: str, order: Order, context: Mapping[str, Any] | None = None) -> int:
    """Experimental. Send the email of ``kind`` about ``order``. Returns how many went out."""
    from karni_commerce.services import order_link

    template, audience = KINDS[kind]
    values = {
        "order": order,
        "lines": list(order.lines.all()),
        "link": order_link(order),
        **dict(context or {}),
    }
    return send_templated(template, to=_recipients(order, audience), context=values, kind=kind)
