"""Deposits and their balance link, a line's own hold with its expiry, and free orders of
every kind: the parts of the order path a booking, a course or a quote need."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.core import mail
from django.utils import timezone
from karni.exceptions import KarniImproperlyConfigured
from karni.testing import capture_events, deliver_now
from karni.timeline.models import TimelineEntry
from karni_payments.services import create_checkout
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from karni_commerce import services
from karni_commerce.models import Cart, Coupon, Invoice, Order
from karni_commerce.sellables import Price, Sellable, hold_of
from tests.conftest import ADDRESS, cart_with, pay, place
from tests.testapp.models import Booking, Gadget, Slot, Workshop
from tests.testapp.sellables import BookingSellable

pytestmark = pytest.mark.django_db

MakeGadget = Callable[..., Gadget]
MakeSlot = Callable[..., Slot]
MakeWorkshop = Callable[..., Workshop]


def fresh(row: Any) -> Any:
    row.refresh_from_db()
    return row


def booking_of(order: Order) -> Booking:
    line = order.lines.get(kind="booking")
    return Booking.objects.get(order_line=str(line.pk))


def as_user(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


# -- deposits -------------------------------------------------------------------------------


def test_a_deposit_is_offered_only_when_every_line_allows_one(
    make_slot: MakeSlot, make_gadget: MakeGadget
) -> None:
    visit = make_slot(price=Decimal("50.00"), deposit=Decimal("10.00"), seats=3)
    alone = services.quote_cart(cart_with(("booking", visit, 2)), address=ADDRESS)
    assert alone.total == Decimal("100.00") and alone.deposit == Decimal("20.00")
    mixed = cart_with(("booking", visit, 1), ("gadget", make_gadget(), 1))
    assert services.quote_cart(mixed, address=ADDRESS).deposit is None
    with pytest.raises(ValidationError, match="cannot be paid by a deposit"):
        place(mixed, deposit=True)
    no_deposit = make_slot(deposit=Decimal("0.00"))
    assert services.quote_cart(cart_with(("booking", no_deposit, 1))).deposit is None


def test_a_deposit_secures_the_booking_and_the_balance_pays_the_rest(
    make_slot: MakeSlot,
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: Any,
) -> None:
    taken: list[str] = []
    original = BookingSellable.on_paid

    def counted(self: BookingSellable, line: Any) -> None:
        taken.append(str(line.pk))
        original(self, line)

    monkeypatch.setattr(BookingSellable, "on_paid", counted)
    visit = make_slot(price=Decimal("50.00"), deposit=Decimal("10.00"))
    order = place(cart_with(("booking", visit, 1)), email="ana@example.com", deposit=True)
    assert (order.deposit, order.due_now, booking_of(order).status) == (
        Decimal("10.00"),
        Decimal("10.00"),
        "held",
    )
    with django_capture_on_commit_callbacks(execute=True):
        order = pay(order)
    assert order.status == "part_paid" and order.amount_paid == Decimal("10.00")
    assert order.balance == order.due_now == Decimal("40.00") and order.paid_at is None
    assert booking_of(order).status == "confirmed" and len(taken) == 1
    assert order.payments.get().purpose == "deposit"
    assert not Invoice.objects.filter(order=order).exists()
    sent = {message.extra_headers["X-Karni-Kind"]: message for message in mail.outbox}
    assert set(sent) == {"commerce.balance_due", "commerce.new_order"}
    balance_mail = sent["commerce.balance_due"]
    assert balance_mail.subject == f"Order {order.number}: 40.00 EUR to pay"
    assert "Still to pay: 40.00 EUR" in balance_mail.body
    assert services.order_link(order) in balance_mail.body
    assert "has its deposit paid (10.00 EUR)" in sent["commerce.new_order"].body
    # The hold no longer matters: a part-paid order is the buyer's.
    assert services.release_expired(now=timezone.now() + timedelta(hours=2)) == 0
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        order = pay(order)
    assert order.status == "paid" and order.amount_paid == Decimal("50.00")
    assert sorted(link.purpose for link in order.payments.all()) == ["balance", "deposit"]
    assert len(taken) == 1  # the balance takes nothing twice
    assert Invoice.objects.filter(order=order).exists()
    assert [message.extra_headers["X-Karni-Kind"] for message in mail.outbox] == [
        "commerce.order_paid"
    ]


def test_the_checkout_validator_asks_for_the_deposit_then_the_balance(
    make_slot: MakeSlot,
) -> None:
    order = place(cart_with(("booking", make_slot(), 1)), deposit=True)
    with pytest.raises(ValidationError, match="owes 10.00 EUR"):
        create_checkout(
            None,
            amount=Decimal("50.00"),
            currency="eur",
            success_url="http://localhost:5173/ok",
            cancel_url="http://localhost:5173/no",
            metadata={"commerce_order": str(order.pk)},
        )
    order = pay(order)
    with pytest.raises(ValidationError, match="owes 40.00 EUR"):
        create_checkout(
            None,
            amount=Decimal("10.00"),
            currency="eur",
            success_url="http://localhost:5173/ok",
            cancel_url="http://localhost:5173/no",
            metadata={"commerce_order": str(order.pk)},
        )


def test_a_declined_deposit_frees_the_slot_and_a_retry_holds_it_again(
    make_slot: MakeSlot,
) -> None:
    visit = make_slot(seats=1)
    order = pay(place(cart_with(("booking", visit, 1)), deposit=True), "decline")
    assert order.status == "failed" and fresh(visit).free_seats == 1
    assert booking_of(order).status == "released"
    order = pay(order)
    assert order.status == "part_paid" and fresh(visit).free_seats == 0
    assert booking_of(order).status == "confirmed"
    assert {link.purpose for link in order.payments.all()} == {"deposit"}


def test_a_failed_balance_payment_leaves_the_order_part_paid(make_slot: MakeSlot) -> None:
    visit = make_slot()
    order = pay(place(cart_with(("booking", visit, 1)), deposit=True))
    order = pay(order, "decline")
    assert order.status == "part_paid" and booking_of(order).status == "confirmed"
    assert fresh(visit).free_seats == 0
    assert pay(order).status == "paid"


def test_cancelling_a_part_paid_order_gives_the_deposit_back(
    make_slot: MakeSlot, django_capture_on_commit_callbacks: Any
) -> None:
    visit = make_slot()
    order = pay(place(cart_with(("booking", visit, 1)), deposit=True))
    with django_capture_on_commit_callbacks(execute=True):
        services.cancel(order, "the client cannot come")
    assert fresh(order).status == "cancelled" and fresh(visit).free_seats == 1
    assert booking_of(order).status == "cancelled"
    assert order.refunds.get().amount == Decimal("10.00")


def test_staff_send_the_balance_link_of_a_part_paid_order_only(
    make_slot: MakeSlot, django_capture_on_commit_callbacks: Any
) -> None:
    order = place(cart_with(("booking", make_slot(), 1)), email="ana@example.com", deposit=True)
    with pytest.raises(ValidationError, match="deposit paid"):
        services.request_balance(order)
    order = pay(order)
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        link = services.request_balance(order)
    assert link == services.order_link(order)
    [message] = mail.outbox
    assert message.to == ["ana@example.com"] and link in message.body
    assert message.extra_headers["X-Karni-Kind"] == "commerce.balance_due"


def test_the_deposit_is_published_and_on_the_buyers_timeline(make_slot: MakeSlot) -> None:
    with capture_events() as published:
        order = pay(place(cart_with(("booking", make_slot(), 1)), deposit=True))
    published.assert_published(
        "commerce.order.part_paid",
        subject=order,
        person=order.person_id,
        amount_paid="10.00",
        balance="40.00",
        currency="EUR",
    )
    published.assert_not_published("commerce.order.paid")
    deliver_now()
    entry = TimelineEntry.objects.get(person=order.person_id, kind="commerce.order.part_paid")
    assert entry.title == f"Deposit paid on order {order.number}"
    assert entry.body == "10.00 EUR paid, 40.00 EUR to pay"


# -- holds with an expiry ---------------------------------------------------------------------


def test_a_lines_short_hold_cuts_the_orders_hold_and_frees_the_slot(
    make_slot: MakeSlot, make_gadget: MakeGadget
) -> None:
    visit, lamp = make_slot(seats=1), make_gadget(stock=2)
    order = place(cart_with(("booking", visit, 1), ("gadget", lamp, 1)))
    assert order.hold_until is not None
    held = (order.hold_until - order.created_at).total_seconds() / 60
    assert 14.9 < held <= 15.1  # the booking's 15 minutes, not the project's 30
    assert booking_of(order).expires_at == order.hold_until
    assert services.release_expired(now=timezone.now() + timedelta(minutes=10)) == 0
    assert services.release_expired(now=timezone.now() + timedelta(minutes=16)) == 1
    assert fresh(order).status == "cancelled" and booking_of(order).status == "released"
    assert (fresh(visit).free_seats, fresh(lamp).available) == (1, 2)


def test_an_order_without_a_short_hold_keeps_the_projects(make_gadget: MakeGadget) -> None:
    order = place(cart_with(("gadget", make_gadget(), 1)))
    assert order.hold_until is not None
    assert 29.9 < (order.hold_until - order.created_at).total_seconds() / 60 <= 30.1


def test_a_staff_order_holds_for_the_manual_time_or_a_lines_shorter_one(
    manager: Any, make_slot: MakeSlot, make_gadget: MakeGadget
) -> None:
    def minutes(order: Order) -> float:
        assert order.hold_until is not None
        return (order.hold_until - order.created_at).total_seconds() / 60

    lamp = make_gadget(stock=3)
    by_hand = services.place_manual_order(
        [("gadget", str(lamp.pk), 1, {})], staff=manager, email="ana@example.com", send_link=False
    )
    assert 2879 < minutes(by_hand) <= 2881
    slot = services.place_manual_order(
        [("booking", str(make_slot().pk), 1, {})],
        staff=manager,
        email="ana@example.com",
        send_link=False,
        deposit=True,
    )
    assert 14.9 < minutes(slot) <= 15.1 and slot.deposit == Decimal("10.00")


def test_a_retry_holds_the_order_as_long_as_it_was_held(make_slot: MakeSlot) -> None:
    order = pay(place(cart_with(("booking", make_slot(), 1))), "decline")
    later = timezone.now() + timedelta(minutes=5)
    from unittest import mock

    with mock.patch("django.utils.timezone.now", return_value=later):
        services.open_payment(order)
    order.refresh_from_db()
    assert order.hold_until is not None
    assert abs((order.hold_until - later).total_seconds() / 60 - 15) < 0.2


def test_a_hold_below_a_minute_is_a_configuration_error(make_gadget: MakeGadget) -> None:
    class Hasty(Sellable):
        kind = "hasty"
        model = Gadget

        def price(self, item: Any, options: Any, buyer: Any) -> Price:
            return Price(unit=Decimal("1.00"))

        def hold_minutes(self, item: Any, options: Any) -> int:
            return 0

    with pytest.raises(KarniImproperlyConfigured, match="COM003"):
        hold_of(Hasty(), make_gadget(), {})


# -- free orders, whatever they sell ------------------------------------------------------------


def test_a_free_order_of_any_kind_is_paid_when_placed(
    make_slot: MakeSlot, make_workshop: MakeWorkshop, django_capture_on_commit_callbacks: Any
) -> None:
    open_door = make_slot(price=Decimal("0.00"), deposit=Decimal("0.00"))
    open_day = make_workshop(price=Decimal("0.00"))
    with django_capture_on_commit_callbacks(execute=True):
        order = place(cart_with(("booking", open_door, 1), ("seat", open_day, 1)))
    assert order.status == "paid" and order.paid_at is not None
    assert not order.payments.exists() and order.total == Decimal("0.00")
    assert booking_of(order).status == "confirmed" and fresh(open_day).enrolled == 1
    assert services.open_payment(order) is None
    assert [message.extra_headers["X-Karni-Kind"] for message in mail.outbox] == [
        "commerce.order_paid",
        "commerce.new_order",
    ]


def test_a_coupon_that_takes_it_all_settles_the_order_and_takes_the_stock(
    make_gadget: MakeGadget,
) -> None:
    lamp = make_gadget(stock=3, price=Decimal("20.00"))
    Coupon.objects.create(code="ALL", kind=Coupon.Kind.PERCENT, amount=Decimal("100"))
    cart = cart_with(("gadget", lamp, 1))
    services.apply_coupon(cart, "ALL")
    order = place(cart)
    assert order.status == "paid" and order.total == Decimal("0.00")
    assert (fresh(lamp).stock, lamp.available) == (2, 2)


def test_a_free_order_by_hand_sends_the_confirmation_not_a_payment_link(
    manager: Any, make_workshop: MakeWorkshop, django_capture_on_commit_callbacks: Any
) -> None:
    open_day = make_workshop(price=Decimal("0.00"))
    with django_capture_on_commit_callbacks(execute=True):
        order = services.place_manual_order(
            [("seat", str(open_day.pk), 1, {})], staff=manager, email="ana@example.com"
        )
    assert order.status == "paid"
    kinds = [message.extra_headers["X-Karni-Kind"] for message in mail.outbox]
    assert "commerce.payment_request" not in kinds and "commerce.order_paid" in kinds


def test_a_free_checkout_answers_no_payment_address(
    api: APIClient, make_workshop: MakeWorkshop
) -> None:
    open_day = make_workshop(price=Decimal("0.00"))
    cart = cart_with(("seat", open_day, 1))
    placed = api.post(
        "/api/carts/current/checkout/",
        {"email": "guest@example.com", "billing": ADDRESS},
        format="json",
        HTTP_X_CART_TOKEN=cart.token,
    )
    assert placed.status_code == 201, placed.data
    assert placed.data["url"] is None
    assert Order.objects.get(number=placed.data["number"]).status == "paid"


# -- the API ------------------------------------------------------------------------------------


def test_the_api_takes_a_deposit_shows_the_balance_and_sends_its_link(
    api: APIClient,
    buyer: Any,
    clerk: Any,
    make_slot: MakeSlot,
    django_capture_on_commit_callbacks: Any,
) -> None:
    visit = make_slot(price=Decimal("50.00"), deposit=Decimal("15.00"))
    cart = cart_with(("booking", visit, 1))
    quoted = api.post(
        "/api/carts/current/quote/",
        {"address": {"country": "FR"}},
        format="json",
        HTTP_X_CART_TOKEN=cart.token,
    )
    assert quoted.status_code == 200 and quoted.data["deposit"] == "15.00"
    placed = api.post(
        "/api/carts/current/checkout/",
        {"email": "guest@example.com", "billing": ADDRESS, "pay": "deposit"},
        format="json",
        HTTP_X_CART_TOKEN=cart.token,
    )
    assert placed.status_code == 201, placed.data
    assert placed.data["url"].startswith("https://checkout.test/pay/")
    query = {"number": placed.data["number"], "key": placed.data["key"]}
    looked = api.get("/api/orders/lookup/", query).data
    assert (looked["deposit"], looked["due_now"], looked["balance"]) == ("15.00", "15.00", "50.00")
    order = pay(Order.objects.get(number=placed.data["number"]))
    looked = api.get("/api/orders/lookup/", query).data
    assert looked["status"] == "part_paid" and looked["payable"] is True
    assert (looked["due_now"], looked["balance"]) == ("35.00", "35.00")
    again = api.post("/api/orders/pay/", query, format="json")
    assert again.status_code == 200 and again.data["url"].startswith("https://checkout.test/pay/")
    staff = as_user(clerk).get(f"/api/orders/{order.pk}/staff/").data
    assert staff["can_request_balance"] is True and staff["can_cancel"] is True
    with django_capture_on_commit_callbacks(execute=True):
        sent = as_user(clerk).post(f"/api/orders/{order.pk}/balance-link/")
    assert sent.status_code == 200 and sent.data["link"] == services.order_link(order)
    assert mail.outbox[-1].extra_headers["X-Karni-Kind"] == "commerce.balance_due"
    assert as_user(buyer).post(f"/api/orders/{order.pk}/balance-link/").status_code in (403, 404)


def test_a_staff_order_may_ask_for_a_deposit(manager: Any, make_slot: MakeSlot) -> None:
    visit = make_slot(deposit=Decimal("5.00"))
    line = {"kind": "booking", "item": str(visit.pk), "quantity": 1}
    quoted = as_user(manager).post("/api/orders/manual/quote/", {"lines": [line]}, format="json")
    assert quoted.status_code == 200 and quoted.data["deposit"] == "5.00"
    placed = as_user(manager).post(
        "/api/orders/manual/",
        {
            "email": "ana@example.com",
            "billing": ADDRESS,
            "lines": [line],
            "pay": "deposit",
            "send_link": False,
        },
        format="json",
    )
    assert placed.status_code == 201, placed.data
    assert Order.objects.get(pk=placed.data["id"]).deposit == Decimal("5.00")


def test_an_empty_cart_offers_no_deposit() -> None:
    assert services.quote_cart(Cart.objects.create()).deposit is None
