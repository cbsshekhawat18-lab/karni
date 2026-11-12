"""Commerce's reactions: a payment or a refund moves its order, and an order's moves send mail.

Karni imports this module at startup (``karni.events`` autodiscovery).
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.dispatch import receiver
from karni_payments.events import payment_status_changed, refund_status_changed
from karni_payments.models import Payment, Refund

from karni_commerce import events, messages, services
from karni_commerce.models import Order, OrderNote, OrderRefund


@receiver(payment_status_changed)
def move_the_order(sender: Any, payment: Payment, **kwargs: Any) -> None:
    """The provider settled a payment: its order is paid, or failed."""
    services.settle(payment)


@receiver(refund_status_changed)
def refund_the_order(sender: Any, refund: Refund, **kwargs: Any) -> None:
    """The provider confirmed a refund: its order's lines and amounts follow."""
    services.settle_refund(refund)


def _mail(kind: str, order: Order, **context: Any) -> None:
    pk = order.pk

    def send() -> None:
        found = Order.objects.filter(pk=pk).first()
        if found is not None:
            messages.send(kind, found, context)

    transaction.on_commit(send)


@receiver(events.order_paid)
def confirm_the_order(sender: Any, order: Order, **kwargs: Any) -> None:
    """The buyer's confirmation, and the staff's new-order email."""
    _mail("commerce.order_paid", order)
    _mail("commerce.new_order", order)


@receiver(events.order_cancelled)
def say_it_was_cancelled(sender: Any, order: Order, **kwargs: Any) -> None:
    _mail("commerce.order_cancelled", order)


@receiver(events.order_refunded)
def say_it_was_refunded(sender: Any, order: Order, refund: OrderRefund, **kwargs: Any) -> None:
    _mail("commerce.order_refunded", order, refund=refund)


@receiver(events.order_note_added)
def send_the_note(sender: Any, order: Order, note: OrderNote, **kwargs: Any) -> None:
    """A note to the customer goes to the buyer by email. An internal note stays here."""
    if note.kind == OrderNote.Kind.CUSTOMER:
        _mail("commerce.order_note", order, note=note)
