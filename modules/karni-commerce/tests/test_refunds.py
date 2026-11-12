"""Refunds by line or by amount, settled when the provider confirms them."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from karni_commerce import services
from tests.conftest import cart_with, pay, place, refund_webhook
from tests.testapp.models import Gadget, Workshop

pytestmark = pytest.mark.django_db


def fresh(row: Any) -> Any:
    row.refresh_from_db()
    return row


def test_a_refund_by_line_returns_the_items_when_asked(
    make_gadget: Callable[..., Gadget], django_capture_on_commit_callbacks: Any
) -> None:
    lamp = make_gadget(stock=5, price=Decimal("20.00"))
    order = pay(place(cart_with(("gadget", lamp, 3))))
    [line] = order.lines.all()
    record = services.refund(order, lines={str(line.pk): 2}, restock=True, reason="damaged")
    assert record.amount == Decimal("40.00") and fresh(order).status == "paid"
    with django_capture_on_commit_callbacks(execute=True):
        refund_webhook(order)
    order.refresh_from_db()
    assert order.status == "part_refunded" and order.amount_refunded == Decimal("40.00")
    assert fresh(line).quantity_refunded == 2
    assert (fresh(lamp).stock, lamp.available) == (4, 4)
    assert fresh(record).settled_at is not None
    [message] = [m for m in mail.outbox if "refund" in m.subject.lower()]
    assert "40.00 EUR" in message.body


def test_the_rest_by_amount_makes_the_order_refunded_without_restock(
    make_gadget: Callable[..., Gadget],
) -> None:
    lamp = make_gadget(stock=5, price=Decimal("20.00"))
    order = pay(place(cart_with(("gadget", lamp, 2))))
    services.refund(order, amount=Decimal("15.00"))
    refund_webhook(order)
    services.refund(fresh(order), amount=Decimal("25.00"))
    refund_webhook(order)
    order.refresh_from_db()
    assert order.status == "refunded" and order.amount_refunded == Decimal("40.00")
    assert fresh(lamp).stock == 3  # by amount: nothing comes back to the shelf


def test_no_more_than_was_paid_goes_back(make_gadget: Callable[..., Gadget]) -> None:
    order = pay(place(cart_with(("gadget", make_gadget(price=Decimal("20.00")), 1))))
    services.refund(order, amount=Decimal("15.00"))  # still pending at the provider
    with pytest.raises(ValidationError, match="At most 5.00 EUR"):
        services.refund(order, amount=Decimal("6.00"))
    [line] = order.lines.all()
    with pytest.raises(ValidationError, match="at most 1 can be refunded"):
        services.refund(order, lines={str(line.pk): 2})


def test_an_order_that_took_no_money_cannot_be_refunded(
    make_gadget: Callable[..., Gadget],
) -> None:
    order = place(cart_with(("gadget", make_gadget(), 1)))
    with pytest.raises(ValidationError, match="took no money"):
        services.refund(order, amount=Decimal("1.00"))


def test_a_failed_refund_changes_nothing(make_gadget: Callable[..., Gadget]) -> None:
    order = pay(place(cart_with(("gadget", make_gadget(), 1))))
    record = services.refund(order, amount=Decimal("5.00"))
    refund_webhook(order, "refund_failed")
    assert fresh(order).amount_refunded == Decimal("0") and fresh(record).settled_at is None
    services.refund(order, amount=Decimal("20.00"))  # the failed one no longer counts


def test_the_adapter_limits_what_a_line_refunds(
    make_workshop: Callable[..., Workshop],
) -> None:
    """A workshop seat is not refunded once the workshop started (its refund_limit)."""
    pottery = make_workshop(starts_at=timezone.now() + timedelta(minutes=40))
    order = pay(place(cart_with(("seat", pottery, 1))))
    Workshop.objects.filter(pk=pottery.pk).update(starts_at=timezone.now() - timedelta(minutes=5))
    [line] = order.lines.all()
    with pytest.raises(ValidationError, match="At most|can be refunded"):
        services.refund(order, lines={str(line.pk): 1})
