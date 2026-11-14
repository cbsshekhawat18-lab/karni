"""Commerce's reactions: a payment or a refund moves its order, an order's moves send mail,
and each move is published as a family event (``commerce.order.*``).

Karni imports this module at startup (``karni.events`` autodiscovery).
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.dispatch import receiver
from karni.events import publish
from karni_payments.events import payment_status_changed, refund_status_changed
from karni_payments.models import Payment, Refund

from karni_commerce import events, messages, services
from karni_commerce.models import Order, OrderLine, OrderNote, OrderRefund


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
    """The buyer's confirmation, and the staff's new-order email (once: an order paid by a
    deposit first told the staff when the deposit came in)."""
    _mail("commerce.order_paid", order)
    if order.deposit <= 0:
        _mail("commerce.new_order", order)


@receiver(events.order_part_paid)
def ask_for_the_balance(sender: Any, order: Order, **kwargs: Any) -> None:
    """The deposit is in: the buyer gets what is left and the link, the staff the order."""
    _mail("commerce.balance_due", order)
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


# -- the family events: commerce.order.* (declared in karni_commerce.events) ----------------


def _lines(order: Order) -> list[dict[str, Any]]:
    rows = OrderLine.objects.filter(order=order).order_by("position")
    return [
        {
            "line": str(line.pk),
            "kind": line.kind,
            "item": line.item,
            "quantity": line.quantity,
            "line_total": f"{line.paid_total:.2f}",
        }
        for line in rows
    ]


def _about(order: Order) -> dict[str, Any]:
    return {"subject": order, "person": order.person_id, "order": str(order.pk)}


@receiver(events.order_placed)
def publish_placed(sender: Any, order: Order, **kwargs: Any) -> None:
    publish(
        "commerce.order.placed",
        **_about(order),
        number=order.number,
        total=f"{order.total:.2f}",
        currency=order.currency,
        lines=_lines(order),
    )


@receiver(events.order_paid)
def publish_paid(sender: Any, order: Order, **kwargs: Any) -> None:
    publish(
        "commerce.order.paid",
        **_about(order),
        number=order.number,
        total=f"{order.total:.2f}",
        currency=order.currency,
        paid_at=order.paid_at,
        lines=_lines(order),
    )


@receiver(events.order_part_paid)
def publish_part_paid(sender: Any, order: Order, **kwargs: Any) -> None:
    publish(
        "commerce.order.part_paid",
        **_about(order),
        number=order.number,
        amount_paid=f"{order.amount_paid:.2f}",
        balance=f"{order.balance:.2f}",
        currency=order.currency,
    )


@receiver(events.order_cancelled)
def publish_cancelled(sender: Any, order: Order, reason: str = "", **kwargs: Any) -> None:
    publish(
        "commerce.order.cancelled",
        **_about(order),
        number=order.number,
        reason=str(reason or ""),
    )


@receiver(events.order_refunded)
def publish_refunded(
    sender: Any, order: Order, refund: OrderRefund, full: bool = False, **kwargs: Any
) -> None:
    known = {str(line.pk): line for line in OrderLine.objects.filter(order=order)}
    lines = [
        {
            "line": key,
            "kind": known[key].kind,
            "item": known[key].item,
            "quantity": quantity,
        }
        for key, quantity in refund.line_quantities().items()
        if key in known
    ]
    publish(
        "commerce.order.refunded",
        **_about(order),
        number=order.number,
        refund=str(refund.pk),
        amount=f"{refund.amount:.2f}",
        currency=order.currency,
        lines=lines,
        full=bool(full),
    )
