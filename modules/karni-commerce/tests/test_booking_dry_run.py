"""A dry run of the booking recipe on commerce's path, before the recipe exists.

The test app's ``booking`` kind (tests/testapp/sellables.py) is what the booking
recipe's adapter will be: checkout books a slot tentatively and holds its seats for
15 minutes, a deposit confirms it, the balance is paid later by the order's link,
a refund follows the policy by the time before the start, and an order not paid in
time frees the slot. The conformance helper (karni_commerce.testing) runs on it and
on the other kinds.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.core import mail
from django.utils import timezone
from karni.exceptions import KarniAssertionError
from karni.testing import deliver_now
from karni.timeline.models import TimelineEntry
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from karni_commerce import services
from karni_commerce.models import Order, OrderLine
from karni_commerce.sellables import Price, Sellable, register, unregister
from karni_commerce.testing import assert_sellable
from tests.conftest import ADDRESS, cart_with, pay, place, refund_webhook
from tests.testapp.models import Booking, Gadget, Slot, Workshop

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


def test_a_guest_books_with_a_deposit_and_pays_the_balance_by_its_link(
    api: APIClient, make_slot: MakeSlot, django_capture_on_commit_callbacks: Any
) -> None:
    visit = make_slot(title="Tuning, 1 hour", price=Decimal("80.00"), deposit=Decimal("20.00"))
    added = api.post(
        "/api/carts/current/lines/",
        {"kind": "booking", "item": str(visit.pk), "quantity": 1},
        format="json",
    )
    assert added.status_code == 200, added.data
    token = added.data["token"]
    [line] = added.data["lines"]
    assert line["name"] == "Booking: Tuning, 1 hour" and line["details"][0]["label"] == "When"
    assert added.data["needs_shipping"] is False
    placed = api.post(
        "/api/carts/current/checkout/",
        {"email": "rui@example.com", "name": "Rui Costa", "billing": ADDRESS, "pay": "deposit"},
        format="json",
        HTTP_X_CART_TOKEN=token,
    )
    assert placed.status_code == 201, placed.data
    order = Order.objects.get(number=placed.data["number"])
    assert booking_of(order).status == "held" and fresh(visit).free_seats == 0
    with django_capture_on_commit_callbacks(execute=True):
        order = pay(order)
    assert order.status == "part_paid" and booking_of(order).status == "confirmed"
    balance_mail = next(
        message
        for message in mail.outbox
        if message.extra_headers["X-Karni-Kind"] == "commerce.balance_due"
    )
    assert balance_mail.to == ["rui@example.com"] and "60.00 EUR" in balance_mail.body
    with django_capture_on_commit_callbacks(execute=True):
        order = pay(order)  # the balance, from the link in the email
    assert order.status == "paid" and order.amount_paid == Decimal("80.00")
    assert booking_of(order).status == "confirmed" and fresh(visit).free_seats == 0
    deliver_now()
    kinds = set(TimelineEntry.objects.filter(person=order.person_id).values_list("kind", flat=True))
    assert {"commerce.order.placed", "commerce.order.part_paid", "commerce.order.paid"} <= kinds
    assert order.person is not None and order.person.email == "rui@example.com"


def test_a_refund_follows_the_policy_by_the_time_before_the_start(make_slot: MakeSlot) -> None:
    early = pay(place(cart_with(("booking", make_slot(seats=2), 2))))
    line = early.lines.get()
    services.refund(early, lines={str(line.pk): 1})
    refund_webhook(early)
    assert fresh(early).status == "part_refunded" and early.amount_refunded == Decimal("50.00")
    slot = Slot.objects.get(pk=line.item)
    assert slot.free_seats == 1  # the refunded seat is free again
    soon = make_slot(starts_at=timezone.now() + timedelta(days=2))
    late = pay(place(cart_with(("booking", soon, 1))))
    Slot.objects.filter(pk=soon.pk).update(starts_at=timezone.now() + timedelta(hours=3))
    with pytest.raises(ValidationError, match="Nothing of these lines can be refunded now"):
        services.refund(late, lines={str(late.lines.get().pk): 1})


def test_a_product_and_a_booking_in_one_checkout(
    make_slot: MakeSlot, make_gadget: MakeGadget
) -> None:
    visit, lamp = make_slot(seats=1), make_gadget(stock=2)
    order = pay(place(cart_with(("booking", visit, 1), ("gadget", lamp, 1))))
    assert order.status == "paid" and order.total == Decimal("70.00")
    assert booking_of(order).status == "confirmed" and fresh(lamp).stock == 1
    failed = pay(
        place(cart_with(("booking", make_slot(seats=1), 1), ("gadget", lamp, 1))), "decline"
    )
    assert failed.status == "failed" and booking_of(failed).status == "released"
    released = Slot.objects.get(pk=failed.lines.get(kind="booking").item)
    assert released.free_seats == 1 and fresh(lamp).available == 1


def test_two_guests_never_get_the_last_seat(make_slot: MakeSlot) -> None:
    last = make_slot(seats=1)
    first, second = cart_with(("booking", last, 1)), cart_with(("booking", last, 1))
    place(first)
    with pytest.raises(ValidationError, match="fully booked|sold out"):
        place(second)
    assert Booking.objects.filter(slot=last).count() == 1


def test_a_slot_that_started_cannot_be_booked(make_slot: MakeSlot) -> None:
    gone = make_slot(starts_at=timezone.now() - timedelta(minutes=1))
    with pytest.raises(ValidationError, match="has started"):
        cart_with(("booking", gone, 1))


# -- the conformance helper ---------------------------------------------------------------------


def test_every_kind_of_the_test_app_keeps_the_commerce_contract(
    make_slot: MakeSlot, make_gadget: MakeGadget, make_workshop: MakeWorkshop
) -> None:
    visit = make_slot(seats=3)
    report = assert_sellable("booking", visit, quantity=2)
    assert report.available == 3 and report.checked == [
        "reads",
        "hold and release",
        "paid and cancelled",
        "paid and refunded",
    ]
    assert fresh(visit).free_seats == 3 and not Booking.objects.exists()  # rolled back
    assert not Order.objects.exists()
    assert assert_sellable("gadget", make_gadget(stock=4), options={"colour": "red"}).available == 4
    assert assert_sellable("seat", make_workshop(seats=5)).available == 5
    assert assert_sellable("booking", make_slot(price=Decimal("0"), deposit=Decimal("0")))


class _Leaky(Sellable):
    """An adapter that forgets to let its hold go: what the helper is for."""

    kind = "leaky"
    model = Slot

    def price(self, item: Slot, options: Any, buyer: Any) -> Price:
        return Price(unit=Decimal("5.00"))

    def available(self, item: Slot, options: Any) -> int:
        return int(item.free_seats)

    def hold(self, line: OrderLine) -> None:
        from karni.capacity import reserve

        reserve(Slot.objects.get(pk=line.item), line.quantity)


class _Writer(_Leaky):
    kind = "writer"

    def name(self, item: Slot, options: Any) -> str:
        Slot.objects.filter(pk=item.pk).update(title=item.title)
        return item.title


@pytest.fixture
def leaky() -> Any:
    register(_Leaky)
    register(_Writer)
    yield
    unregister("leaky")
    unregister("writer")


def test_the_helper_names_a_hook_that_breaks_the_contract(leaky: None, make_slot: MakeSlot) -> None:
    slot = make_slot(seats=2)
    with pytest.raises(KarniAssertionError, match=r"COM002.*release step.*2 should be left, 1"):
        assert_sellable("leaky", slot)
    with pytest.raises(KarniAssertionError, match="COM002.*wrote to the database"):
        assert_sellable("writer", slot)
    with pytest.raises(KarniAssertionError, match="COM002.*no adapter sells 'ghost'"):
        assert_sellable("ghost", slot)
    with pytest.raises(KarniAssertionError, match="COM002.*refused 3"):
        assert_sellable("booking", slot, quantity=3)
    assert fresh(slot).free_seats == 2
