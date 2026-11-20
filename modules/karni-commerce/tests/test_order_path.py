"""The order path's rules: the cart, checkout, the holds, the settlement and cancelling."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.core import mail
from django.db import IntegrityError, transaction
from django.dispatch import receiver
from django.utils import timezone
from karni.lifecycle import IllegalTransition
from karni_payments.models import Payment
from rest_framework.exceptions import ValidationError

from karni_commerce import events, services
from karni_commerce.models import Cart, CartLine, Order
from tests.conftest import ADDRESS, cart_with, pay, place
from tests.testapp.models import Gadget, Workshop

pytestmark = pytest.mark.django_db

MakeGadget = Callable[..., Gadget]
MakeWorkshop = Callable[..., Workshop]


def fresh(row: Any) -> Any:
    row.refresh_from_db()
    return row


def test_a_line_is_priced_by_its_adapter_and_refused_past_what_is_left(
    make_gadget: MakeGadget,
) -> None:
    lamp = make_gadget(price=Decimal("20.00"), sale_price=Decimal("15.00"), stock=3)
    cart = Cart.objects.create()
    services.set_line(cart, "gadget", str(lamp.pk), 2)
    services.set_line(cart, "gadget", str(lamp.pk), 1, add=True)
    [priced] = services.cart_lines(cart)
    assert (priced.line.quantity, priced.unit_price, priced.line_total) == (
        3,
        Decimal("15.00"),
        Decimal("45.00"),
    )
    assert priced.price is not None and priced.price.compare_at == Decimal("20.00")
    with pytest.raises(ValidationError, match="Only 3 of Lamp left"):
        services.set_line(cart, "gadget", str(lamp.pk), 4)
    services.set_line(cart, "gadget", str(lamp.pk), 0)
    assert not cart.lines.exists()


def test_an_unknown_kind_or_item_is_refused(make_gadget: MakeGadget) -> None:
    cart = Cart.objects.create()
    with pytest.raises(ValidationError, match="Nothing called 'ghost'"):
        services.set_line(cart, "ghost", "1", 1)
    with pytest.raises(ValidationError, match="Nothing like that"):
        services.set_line(cart, "gadget", "00000000-0000-0000-0000-000000000000", 1)


def test_checkout_copies_each_line_and_holds_it(make_gadget: MakeGadget) -> None:
    lamp = make_gadget(name="Brass Lamp", sku="BL-1", price=Decimal("30.00"), stock=5)
    order = place(cart_with(("gadget", lamp, 2)))
    lamp.name, lamp.price = "Renamed", Decimal("99.00")
    lamp.save()
    [line] = order.lines.all()
    assert (line.name, line.sku, line.unit_price, line.line_total) == (
        "Brass Lamp",
        "BL-1",
        Decimal("30.00"),
        Decimal("60.00"),
    )
    assert order.subtotal == order.total == Decimal("60.00")
    assert order.status == "pending" and order.currency == "EUR"
    assert order.needs_shipping and order.shipping["city"] == "Lyon"
    assert (fresh(lamp).stock, lamp.available) == (5, 3)
    assert order.hold_until > timezone.now()


def test_two_buyers_of_the_last_item_never_both_get_it(make_gadget: MakeGadget) -> None:
    last = make_gadget(stock=1)
    first, second = cart_with(("gadget", last, 1)), cart_with(("gadget", last, 1))
    place(first)
    with pytest.raises(ValidationError, match="sold out"):
        place(second)
    assert fresh(last).available == 0 and Order.objects.count() == 1
    assert second.lines.count() == 1  # the second cart keeps its line


def test_stock_never_goes_below_zero_in_the_database(make_gadget: MakeGadget) -> None:
    bowl = make_gadget(stock=1)
    with pytest.raises(IntegrityError), transaction.atomic():
        Gadget.objects.filter(pk=bowl.pk).update(available=-1)


def test_payment_takes_the_held_items_and_confirms_by_email(
    make_gadget: MakeGadget, django_capture_on_commit_callbacks: Any
) -> None:
    lamp = make_gadget(stock=5)
    with django_capture_on_commit_callbacks(execute=True):
        order = pay(place(cart_with(("gadget", lamp, 2)), email="ines@example.com"))
    assert order.status == "paid" and order.paid_at is not None
    assert order.amount_paid == order.total
    assert (fresh(lamp).stock, lamp.available) == (3, 3)
    subjects = {message.subject: message.to for message in mail.outbox}
    assert subjects[f"Order {order.number} is confirmed"] == ["ines@example.com"]
    assert subjects[f"New order {order.number}: 40.00 EUR"] == ["orders@example.com"]
    confirmation = next(m for m in mail.outbox if m.to == ["ines@example.com"])
    assert confirmation.extra_headers["X-Karni-Kind"] == "commerce.order_paid"
    assert f"/orders/{order.number}?key={order.key}" in confirmation.body


def test_a_declined_payment_releases_the_items_and_can_be_tried_again(
    make_gadget: MakeGadget,
) -> None:
    lamp = make_gadget(stock=4)
    order = pay(place(cart_with(("gadget", lamp, 3))), "decline")
    assert order.status == "failed" and fresh(lamp).available == 4
    order = pay(order)  # the second attempt holds the items again
    assert order.status == "paid" and order.payments.count() == 2
    assert {link.purpose for link in order.payments.all()} == {"full", "retry"}
    assert (fresh(lamp).stock, lamp.available) == (1, 1)


def test_an_order_not_paid_in_time_lets_its_items_go(make_gadget: MakeGadget) -> None:
    pen = make_gadget(stock=2)
    order = place(cart_with(("gadget", pen, 2)))
    assert services.release_expired(now=timezone.now() + timedelta(minutes=31)) == 1
    assert fresh(order).status == "cancelled" and fresh(pen).available == 2
    with pytest.raises(ValidationError, match="not waiting for a payment"):
        services.open_payment(order)


def test_money_for_an_order_that_stopped_waiting_goes_back(
    make_gadget: MakeGadget, django_capture_on_commit_callbacks: Any
) -> None:
    order = place(cart_with(("gadget", make_gadget(), 1)))
    services.open_payment(order)
    services.cancel(order, "changed my mind")
    from karni_payments.test_checkout import settle as settle_payment

    with django_capture_on_commit_callbacks(execute=True):
        settle_payment(order.payments.get().payment, "pay")
    order.refresh_from_db()
    assert order.status == "cancelled" and order.amount_paid == order.total
    assert order.refunds.get().amount == order.total


def test_cancelling_a_paid_order_puts_the_items_back_and_refunds_it(
    make_gadget: MakeGadget, django_capture_on_commit_callbacks: Any
) -> None:
    jar = make_gadget(stock=6)
    order = pay(place(cart_with(("gadget", jar, 2))))
    assert fresh(jar).stock == 4
    with django_capture_on_commit_callbacks(execute=True):
        services.cancel(order, "out of stock at the supplier")
    assert (fresh(jar).stock, jar.available) == (6, 6)
    assert fresh(order).status == "cancelled"
    refund = order.refunds.get()
    assert refund.amount == order.total and not refund.restock
    assert refund.refund.status == "pending"


def test_only_the_allowed_moves_happen(make_gadget: MakeGadget) -> None:
    order = place(cart_with(("gadget", make_gadget(), 1)))
    with pytest.raises(IllegalTransition):
        order.transition("status", "refunded")  # nothing was paid
    pay(order)
    with pytest.raises(IllegalTransition):
        order.transition("status", "pending")
    services.cancel(order)
    with pytest.raises(ValidationError, match="cannot be cancelled"):
        services.cancel(order)


def test_order_numbers_count_up_and_never_repeat(make_gadget: MakeGadget) -> None:
    first = place(cart_with(("gadget", make_gadget(), 1)))
    second = place(cart_with(("gadget", make_gadget(), 1)))
    assert (first.number, second.number) == (1001, 1002)
    assert second.reference == "1002"
    second.delete()  # a soft-deleted order keeps its number
    assert place(cart_with(("gadget", make_gadget(), 1))).number == 1003


def test_a_numbering_function_replaces_the_numbers(make_gadget: MakeGadget, settings: Any) -> None:
    settings.KARNI_COMMERCE_NUMBER = "tests.test_order_path.year_numbers"
    assert place(cart_with(("gadget", make_gadget(), 1))).number == 2026001


def year_numbers(order: Order) -> int:
    return 2026000 + Order.objects.count() + 1


def test_a_second_kind_sells_on_the_same_path(
    make_gadget: MakeGadget, make_workshop: MakeWorkshop
) -> None:
    """A workshop seat (not a product, nothing to ship) beside a gadget in one order."""
    pottery = make_workshop(seats=4)
    lamp = make_gadget(stock=2)
    order = pay(place(cart_with(("seat", pottery, 2), ("gadget", lamp, 1))))
    assert order.status == "paid" and order.total == Decimal("110.00")
    names = sorted(line.name for line in order.lines.all())
    assert names == ["Lamp", "Seat at Pottery basics"]
    assert {line.kind: line.needs_shipping for line in order.lines.all()} == {
        "seat": False,
        "gadget": True,
    }
    assert (fresh(pottery).free_seats, pottery.enrolled) == (2, 2)
    started = make_workshop(starts_at=timezone.now() - timedelta(hours=1))
    with pytest.raises(ValidationError, match="has started"):
        services.set_line(Cart.objects.create(), "seat", str(started.pk), 1)


def test_a_seat_only_order_asks_for_no_shipping_address(make_workshop: MakeWorkshop) -> None:
    order = place(cart_with(("seat", make_workshop(), 1)))
    assert not order.needs_shipping and order.shipping == {}
    assert order.billing == ADDRESS


def test_a_free_order_settles_without_a_payment(make_workshop: MakeWorkshop) -> None:
    open_day = make_workshop(price=Decimal("0.00"))
    order = place(cart_with(("seat", open_day, 1)))
    assert services.open_payment(order) is None
    assert fresh(order).status == "paid" and not order.payments.exists()
    assert fresh(open_day).enrolled == 1


def test_a_visitors_cart_joins_the_persons_cart_at_sign_in(
    make_gadget: MakeGadget, buyer: Any
) -> None:
    lamp, mug = make_gadget(stock=3), make_gadget(name="Mug", stock=10)
    mine = services.find_cart(buyer, None, create=True)
    assert mine is not None
    services.set_line(mine, "gadget", str(lamp.pk), 2)
    visitor = cart_with(("gadget", lamp, 2), ("gadget", mug, 1))
    merged = services.merge(buyer, visitor.token)
    assert merged.pk == mine.pk
    quantities = {line.item: line.quantity for line in merged.lines.all()}
    assert quantities == {str(lamp.pk): 3, str(mug.pk): 1}  # never past what is left
    assert not Cart.objects.filter(pk=visitor.pk).exists()


def test_guest_orders_become_the_persons_once_their_email_is_verified(
    make_gadget: MakeGadget, buyer: Any
) -> None:
    order = place(cart_with(("gadget", make_gadget(), 1)), email="INES@example.com")
    buyer.email_verified = False
    assert services.claim_orders(buyer) == []
    buyer.email_verified = True
    assert services.claim_orders(buyer) == [order]
    assert fresh(order).user == buyer


def test_the_checkout_validator_refuses_a_wrong_amount(make_gadget: MakeGadget) -> None:
    from karni_payments.services import create_checkout

    order = place(cart_with(("gadget", make_gadget(), 1)))
    with pytest.raises(ValidationError, match="owes 20.00 EUR"):
        create_checkout(
            None,
            amount=Decimal("1.00"),
            currency="eur",
            success_url="http://localhost:5173/ok",
            cancel_url="http://localhost:5173/no",
            metadata={"commerce_order": str(order.pk)},
        )
    payment, _session = create_checkout(
        None,
        amount=Decimal("5.00"),
        success_url="http://localhost:5173/ok",
        cancel_url="http://localhost:5173/no",
        metadata={"anything": "else"},
    )
    assert payment.status == Payment.Status.PENDING  # not an order's payment: passed on


def test_what_happens_is_published(make_gadget: MakeGadget) -> None:
    heard: list[str] = []

    @receiver(events.order_placed, weak=False)
    def placed(sender: Any, order: Order, **kwargs: Any) -> None:
        heard.append("placed")

    @receiver(events.order_paid, weak=False)
    def paid(sender: Any, order: Order, **kwargs: Any) -> None:
        heard.append("paid")

    @receiver(events.order_cancelled, weak=False)
    def cancelled(sender: Any, order: Order, reason: str, **kwargs: Any) -> None:
        heard.append(f"cancelled: {reason}")

    try:
        order = pay(place(cart_with(("gadget", make_gadget(), 1))))
        services.cancel(order, "duplicate")
    finally:
        events.order_placed.disconnect(placed)
        events.order_paid.disconnect(paid)
        events.order_cancelled.disconnect(cancelled)
    assert heard == ["placed", "paid", "cancelled: duplicate"]
    assert set(events.EVENTS) >= {"commerce.order.placed", "commerce.order.refunded"}


def test_a_switched_off_kind_sends_no_email(
    make_gadget: MakeGadget, settings: Any, django_capture_on_commit_callbacks: Any
) -> None:
    settings.KARNI_MAIL_DISABLED_KINDS = ["commerce.new_order"]
    with django_capture_on_commit_callbacks(execute=True):
        pay(place(cart_with(("gadget", make_gadget(), 1))))
    assert [message.to for message in mail.outbox] == [["guest@example.com"]]


def test_a_line_left_in_a_cart_is_unique_per_item(make_gadget: MakeGadget) -> None:
    lamp = make_gadget()
    cart = Cart.objects.create()
    CartLine.objects.create(cart=cart, kind="gadget", item=str(lamp.pk), quantity=1)
    with pytest.raises(IntegrityError), transaction.atomic():
        CartLine.objects.create(cart=cart, kind="gadget", item=str(lamp.pk), quantity=1)
