"""The shop's rules on the order path: stock, prices, parcels and their emails."""

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
from karni_commerce import services as commerce
from karni_commerce.fulfilment import report
from rest_framework.exceptions import ValidationError

from shop import events, services
from shop.models import Product, Shipment
from shop.tests.conftest import cart_with, pay, place

pytestmark = pytest.mark.django_db

MakeProduct = Callable[..., Product]


def fresh(product: Product) -> Product:
    product.refresh_from_db()
    return product


def test_checkout_holds_the_stock_and_the_payment_takes_it(
    make_product: MakeProduct,
) -> None:
    lamp = make_product(stock=5)
    order = place(cart_with((lamp, 2)))
    assert (fresh(lamp).stock, lamp.available) == (5, 3)
    assert order.status == "pending" and order.hold_until > timezone.now()
    pay(order)
    assert order.status == "paid" and order.paid_at is not None
    assert (fresh(lamp).stock, lamp.available) == (3, 3)


def test_two_buyers_of_the_last_item_never_both_get_it(
    make_product: MakeProduct,
) -> None:
    last = make_product(stock=1)
    first, second = cart_with((last, 1)), cart_with((last, 1))
    place(first)
    with pytest.raises(ValidationError, match="sold out"):
        place(second)
    assert (fresh(last).stock, last.available) == (1, 0)


def test_an_inactive_product_cannot_be_bought(make_product: MakeProduct) -> None:
    hidden = make_product(active=False)
    with pytest.raises(ValidationError, match="not for sale"):
        cart_with((hidden, 1))


def test_stock_never_goes_below_zero_in_the_database(make_product: MakeProduct) -> None:
    bowl = make_product(stock=1)
    with pytest.raises(IntegrityError), transaction.atomic():
        Product.objects.filter(pk=bowl.pk).update(stock=-1)
    with pytest.raises(IntegrityError), transaction.atomic():
        Product.objects.filter(pk=bowl.pk).update(available=2)  # more than the shelf


def test_a_failed_or_late_payment_gives_the_stock_back(
    make_product: MakeProduct,
) -> None:
    tray, pen = make_product(stock=4), make_product(stock=2)
    failed = pay(place(cart_with((tray, 3))), "decline")
    assert failed.status == "failed" and fresh(tray).available == 4
    late = place(cart_with((pen, 2)))
    assert commerce.release_expired(now=timezone.now() + timedelta(minutes=31)) == 1
    late.refresh_from_db()
    assert late.status == "cancelled" and fresh(pen).available == 2


def test_cancelling_a_paid_order_puts_the_items_back(
    make_product: MakeProduct, django_capture_on_commit_callbacks: Any
) -> None:
    jar = make_product(stock=6)
    order = pay(place(cart_with((jar, 2))))
    assert Shipment.objects.get(order=order).status == "processing"
    with django_capture_on_commit_callbacks(execute=True):
        commerce.cancel(order, "out of stock at the supplier")
    assert (fresh(jar).stock, jar.available) == (6, 6)
    assert Shipment.objects.get(order=order).status == "cancelled"
    assert order.refunds.get().amount == order.total


def test_a_refund_with_restock_puts_the_items_back(make_product: MakeProduct) -> None:
    sack = make_product(stock=3)
    order = pay(place(cart_with((sack, 2))))
    [line] = order.lines.all()
    record = commerce.refund(order, lines={str(line.pk): 1}, restock=True)
    record.refund.status = "succeeded"
    record.refund.save(update_fields=["status", "updated_at"])
    commerce.settle_refund(record.refund)
    assert (fresh(sack).stock, sack.available) == (2, 2)
    order.refresh_from_db()
    assert order.status == "part_refunded"


def test_the_line_keeps_the_name_and_price_of_the_day(
    make_product: MakeProduct,
) -> None:
    board = make_product(name="Oak Board", sku="KIT-9", price=Decimal("30.00"))
    order = place(cart_with((board, 2)))
    board.name, board.price = "Renamed Board", Decimal("99.00")
    board.save()
    [line] = order.lines.all()
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
    assert sorted(line.unit_price for line in order.lines.all()) == [
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


def test_a_paid_order_gets_a_parcel_that_moves_only_forward(
    make_product: MakeProduct, django_capture_on_commit_callbacks: Any
) -> None:
    order = pay(place(cart_with((make_product(name="Brass Lamp"), 1))))
    parcel = Shipment.objects.get(order=order)
    with pytest.raises(ValidationError, match="tracking number"):
        parcel.transition("status", "shipped")
    parcel.refresh_from_db()
    with django_capture_on_commit_callbacks(execute=True):
        services.ship(parcel, "PP123", "Parcel Post")
    assert parcel.status == "shipped" and parcel.shipped_at is not None
    with pytest.raises(IllegalTransition):
        parcel.transition("status", "processing")
    with django_capture_on_commit_callbacks(execute=True):
        services.deliver(parcel)
    assert parcel.delivered_at is not None
    subjects = [message.subject for message in mail.outbox]
    assert f"Order {order.number} is on its way" in subjects
    assert f"Order {order.number} was delivered" in subjects
    shipped = next(m for m in mail.outbox if "on its way" in m.subject)
    assert "Parcel Post tracking number: PP123" in shipped.body
    assert shipped.extra_headers["X-Karni-Kind"] == "shop.shipment_shipped"
    [entry] = report(order)
    assert (entry["label"], entry["detail"]) == (
        "Delivered",
        "Parcel Post tracking PP123",
    )


def test_a_product_running_low_tells_the_staff(
    make_product: MakeProduct, django_capture_on_commit_callbacks: Any
) -> None:
    heard: list[int] = []

    @receiver(events.product_low_stock, weak=False)
    def low(sender: Any, product: Product, **kwargs: Any) -> None:
        heard.append(product.available)

    try:
        with django_capture_on_commit_callbacks(execute=True):
            pay(place(cart_with((make_product(name="Mug", stock=4), 2))))
    finally:
        events.product_low_stock.disconnect(low)
    assert heard == [2]
    staff = [m for m in mail.outbox if m.to == ["orders@example.com"]]
    assert {m.subject for m in staff} >= {"Low stock: Mug (2 left)"}


def test_the_shop_reports_its_events_by_family_name() -> None:
    assert set(events.EVENTS) == {
        "shop.shipment.shipped",
        "shop.shipment.delivered",
        "shop.product.low_stock",
    }


def test_the_product_adapter_keeps_the_commerce_contract(
    make_product: MakeProduct,
) -> None:
    """Commerce's conformance check (karni_commerce.testing): hold, release, paid,
    cancelled and refunded each leave the stock where they should."""
    from karni_commerce.testing import assert_sellable

    lamp = make_product(stock=5, digital=False, backorders=False)
    report = assert_sellable("product", lamp, quantity=2)
    assert report.available == 5 and len(report.checked) == 4
    assert (fresh(lamp).stock, lamp.available) == (5, 5)  # rolled back
