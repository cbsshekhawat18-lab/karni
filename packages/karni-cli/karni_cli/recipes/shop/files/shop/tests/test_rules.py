"""The shop's rules: stock, prices and totals, the order's states and its payment."""

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
from karni_payments.test_checkout import settle
from rest_framework.exceptions import ValidationError

from shop import events, services
from shop.models import Cart, CartItem, Order, Product
from shop.tests.conftest import ADDRESS

pytestmark = pytest.mark.django_db

MakeProduct = Callable[..., Product]


def cart_with(*lines: tuple[Product, int]) -> Cart:
    cart = Cart.objects.create(token=f"t{Cart.objects.count()}")
    for product, quantity in lines:
        CartItem.objects.create(cart=cart, product=product, quantity=quantity)
    return cart


def place(cart: Cart, email: str = "guest@example.com") -> Order:
    return services.place_order(
        cart, customer=None, email=email, billing=ADDRESS, shipping=ADDRESS, note=""
    )


def paid(order: Order) -> Order:
    services.open_payment(order)
    order.refresh_from_db()
    settle(order.payment, "pay")
    order.refresh_from_db()
    return order


def fresh(product: Product) -> Product:
    product.refresh_from_db()
    return product


def test_checkout_reserves_the_stock_and_the_payment_takes_it(
    make_product: MakeProduct,
) -> None:
    lamp = make_product(stock=5)
    order = place(cart_with((lamp, 2)))
    assert (fresh(lamp).stock, lamp.reserved, lamp.available) == (5, 2, 3)
    assert order.status == "pending" and order.reserved_until > timezone.now()
    paid(order)
    assert order.status == "paid" and order.paid_at is not None
    assert (fresh(lamp).stock, lamp.reserved) == (3, 0)


def test_two_buyers_of_the_last_item_never_both_get_it(
    make_product: MakeProduct,
) -> None:
    last = make_product(stock=1)
    first, second = cart_with((last, 1)), cart_with((last, 1))
    stale = Product.objects.get(pk=last.pk)  # what the second buyer's page loaded
    place(first)
    assert stale.available == 1  # the second buyer still sees one
    with pytest.raises(ValidationError, match="sold out"):
        place(second)
    assert (fresh(last).stock, last.reserved) == (1, 1)
    assert Order.objects.count() == 1 and second.cartitem_set.count() == 1


def test_an_order_takes_no_more_than_is_left(make_product: MakeProduct) -> None:
    mug = make_product(stock=3)
    with pytest.raises(ValidationError, match="only 3 left"):
        place(cart_with((mug, 4)))
    assert fresh(mug).reserved == 0 and not Order.objects.exists()


def test_stock_never_goes_below_zero_in_the_database(make_product: MakeProduct) -> None:
    bowl = make_product(stock=1)
    with pytest.raises(IntegrityError), transaction.atomic():
        Product.objects.filter(pk=bowl.pk).update(stock=-1)
    with pytest.raises(IntegrityError), transaction.atomic():
        Product.objects.filter(pk=bowl.pk).update(reserved=2)


def test_a_failed_payment_releases_the_stock(make_product: MakeProduct) -> None:
    tray = make_product(stock=4)
    order = place(cart_with((tray, 3)))
    services.open_payment(order)
    order.refresh_from_db()
    settle(order.payment, "decline")
    order.refresh_from_db()
    assert order.status == "failed"
    assert (fresh(tray).stock, tray.reserved) == (4, 0)


def test_an_order_not_paid_in_time_lets_its_stock_go(make_product: MakeProduct) -> None:
    pen = make_product(stock=2)
    order = place(cart_with((pen, 2)))
    assert services.release_expired(now=timezone.now() + timedelta(minutes=31)) == 1
    order.refresh_from_db()
    assert order.status == "cancelled" and fresh(pen).reserved == 0
    with pytest.raises(ValidationError):
        services.open_payment(order)


def test_cancelling_a_paid_order_returns_its_stock_and_refunds_it(
    make_product: MakeProduct, django_capture_on_commit_callbacks: Any
) -> None:
    jar = make_product(stock=6)
    order = paid(place(cart_with((jar, 2))))
    assert fresh(jar).stock == 4
    with django_capture_on_commit_callbacks(execute=True):
        order.transition("status", "cancelled")
    assert fresh(jar).stock == 6
    refund = order.payment.refunds.get()
    assert refund.amount == order.total


def test_a_refund_returns_the_stock(make_product: MakeProduct) -> None:
    sack = make_product(stock=3)
    order = paid(place(cart_with((sack, 1))))
    order.transition("status", "shipped")
    order.transition("status", "refunded")
    assert fresh(sack).stock == 3


def test_the_line_keeps_the_name_and_price_of_the_day(
    make_product: MakeProduct,
) -> None:
    board = make_product(name="Oak Board", sku="KIT-9", price=Decimal("30.00"))
    order = place(cart_with((board, 2)))
    board.name, board.price = "Renamed Board", Decimal("99.00")
    board.save()
    [line] = order.lines()
    assert (line.name, line.sku, line.unit_price, line.line_total) == (
        "Oak Board",
        "KIT-9",
        Decimal("30.00"),
        Decimal("60.00"),
    )
    assert order.subtotal == order.total == Decimal("60.00")


def test_a_running_sale_sets_the_price(make_product: MakeProduct) -> None:
    now = timezone.now()
    running = make_product(
        price=Decimal("20.00"),
        sale_price=Decimal("15.00"),
        sale_starts=now - timedelta(days=1),
        sale_ends=now + timedelta(days=1),
    )
    later = make_product(
        price=Decimal("20.00"),
        sale_price=Decimal("5.00"),
        sale_starts=now + timedelta(days=2),
    )
    order = place(cart_with((running, 1), (later, 1)))
    assert sorted(line.unit_price for line in order.lines()) == [
        Decimal("15.00"),
        Decimal("20.00"),
    ]
    assert order.total == Decimal("35.00")
    prices = services.with_effective_price(
        Product.objects.filter(pk__in=[running.pk, later.pk])
    )
    assert sorted(p.effective_price for p in prices) == [
        Decimal("15.00"),
        Decimal("20.00"),
    ]


def test_only_the_allowed_moves_happen(make_product: MakeProduct) -> None:
    order = place(cart_with((make_product(), 1)))
    with pytest.raises(IllegalTransition):
        order.transition("status", "shipped")  # not paid yet
    paid(order)
    with pytest.raises(IllegalTransition):
        order.transition("status", "pending")


def test_the_paid_order_mails_its_confirmation(
    make_product: MakeProduct, django_capture_on_commit_callbacks: Any
) -> None:
    lamp = make_product(name="Brass Lamp", price=Decimal("79.00"))
    order = place(cart_with((lamp, 1)), email="mira@example.com")
    with django_capture_on_commit_callbacks(execute=True):
        paid(order)
    [message] = mail.outbox
    assert message.to == ["mira@example.com"]
    assert message.subject == f"Order {order.number} is confirmed"
    assert "1 x Brass Lamp" in message.body and "79.00" in message.body
    assert f"/order/{order.number}?key={order.key}" in message.body


def test_a_payment_that_comes_after_the_order_expired_is_refunded(
    make_product: MakeProduct, django_capture_on_commit_callbacks: Any
) -> None:
    order = place(cart_with((make_product(), 1)))
    services.open_payment(order)
    order.refresh_from_db()
    services.release_expired(now=timezone.now() + timedelta(hours=1))
    with django_capture_on_commit_callbacks(execute=True):
        settle(order.payment, "pay")
    order.refresh_from_db()
    assert order.status == "cancelled"
    assert order.payment.refunds.count() == 1


def test_order_numbers_count_up_from_1001(make_product: MakeProduct) -> None:
    first = place(cart_with((make_product(), 1)))
    second = place(cart_with((make_product(), 1)))
    assert (first.number, second.number) == (1001, 1002)
    assert Order.objects.create(email="a@example.com").number == 1003


def test_what_happens_is_published(make_product: MakeProduct) -> None:
    heard: list[tuple[str, Any]] = []

    @receiver(events.order_placed, weak=False)
    def placed(sender: Any, order: Order, **kwargs: Any) -> None:
        heard.append(("placed", order.number))

    @receiver(events.stock_changed, weak=False)
    def stock(sender: Any, reason: str, quantity: int, **kwargs: Any) -> None:
        heard.append((reason, quantity))

    @receiver(events.stock_low, weak=False)
    def low(sender: Any, product: Product, **kwargs: Any) -> None:
        heard.append(("low", product.stock))

    try:
        order = paid(place(cart_with((make_product(stock=4), 2))))
    finally:
        events.order_placed.disconnect(placed)
        events.stock_changed.disconnect(stock)
        events.stock_low.disconnect(low)
    assert heard == [
        ("reserved", 2),
        ("placed", order.number),
        ("taken", 2),
        ("low", 2),
    ]
    assert order.payment.status == Payment.Status.SUCCEEDED
