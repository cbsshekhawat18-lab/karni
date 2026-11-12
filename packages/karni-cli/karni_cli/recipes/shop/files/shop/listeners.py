"""The shop's reactions: a payment moves its order, and an order's status moves its
stock.

Karni imports this module at startup (``karni.events`` autodiscovery).
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.dispatch import receiver
from karni.events import on_transition
from karni.mail import send_templated
from karni_payments.events import payment_status_changed
from karni_payments.models import Payment

from shop import services
from shop.models import Order


@receiver(payment_status_changed)
def move_the_order(sender: Any, payment: Payment, **kwargs: Any) -> None:
    """The provider settled the payment: its order is paid, or failed."""
    services.settle(payment)


@on_transition(Order, "status", to="paid")
def take_the_stock(order: Order) -> None:
    """A paid order takes its items off the shelf, and the customer gets the confirmation."""
    services.take(order)
    transaction.on_commit(lambda: send_confirmation(order.pk))


@on_transition(Order, "status", to=["failed", "cancelled"], source="pending")
def release_the_stock(order: Order) -> None:
    """An order that was never paid lets go of the stock it held."""
    services.release(order)


@on_transition(
    Order, "status", to=["cancelled", "refunded"], source=list(services.STOCK_TAKEN)
)
def return_the_stock(order: Order) -> None:
    """A paid order that is cancelled or refunded puts its items back and refunds the payment."""
    services.restock(order)
    payment = order.payment
    transaction.on_commit(
        lambda: services.refund(payment, f"order {order.number} {order.status}")
    )


def send_confirmation(order_pk: Any) -> None:
    """The order confirmation: the lines, the totals and the addresses (shop/email/order_paid)."""
    order = Order.objects.filter(pk=order_pk).first()
    if order is None:
        return
    send_templated(
        "shop/email/order_paid",
        to=[order.email],
        context={
            "order": order,
            "lines": order.lines(),
            "link": services.order_link(order),
        },
    )
