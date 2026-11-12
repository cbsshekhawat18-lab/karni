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
(``commerce.order.paid``): the family event bus publishes from these same
places when it is installed.

Override / escape hatch: these are plain :class:`django.dispatch.Signal`
objects. A project that settles orders its own way sends them itself.
"""

from __future__ import annotations

from django.dispatch import Signal

__all__ = [
    "EVENTS",
    "cart_merged",
    "order_cancelled",
    "order_failed",
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
