"""Commerce's family events (commerce.order.*) and the entries they write on the timeline."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

from karni.testing import capture_events, deliver_now
from karni.testing.events import assert_events_declared
from karni.timeline.models import TimelineEntry

from karni_commerce import services
from tests.conftest import cart_with, pay, place, refund_webhook
from tests.testapp.models import Gadget

MakeGadget = Callable[..., Gadget]


def test_every_event_commerce_publishes_is_declared() -> None:
    found = assert_events_declared("karni_commerce")
    assert set(found) >= {
        "commerce.order.placed",
        "commerce.order.paid",
        "commerce.order.part_paid",
        "commerce.order.cancelled",
        "commerce.order.refunded",
        "commerce.invoice.issued",
    }


def test_an_order_publishes_placed_paid_and_refunded_with_its_person(
    manager: Any, make_gadget: MakeGadget
) -> None:
    lamp = make_gadget(price=Decimal("10.00"), stock=9)
    with capture_events() as published:
        order = pay(place(cart_with(("gadget", lamp, 2)), email="ana@example.com"))
        line = order.lines.get()
        services.refund(order, lines={str(line.pk): 1})
        refund_webhook(order)
    placed = published.assert_published(
        "commerce.order.placed",
        subject=order,
        person=order.person_id,
        number=order.number,
        total="20.00",
        currency="EUR",
    )
    assert placed["lines"] == [
        {
            "line": str(line.pk),
            "kind": "gadget",
            "item": str(lamp.pk),
            "quantity": 2,
            "line_total": "20.00",
        }
    ]
    published.assert_published("commerce.order.paid", subject=order, total="20.00")
    published.assert_published("commerce.invoice.issued", order=str(order.pk))
    refunded = published.assert_published(
        "commerce.order.refunded", subject=order, amount="10.00", full=False
    )
    assert refunded["lines"] == [
        {"line": str(line.pk), "kind": "gadget", "item": str(lamp.pk), "quantity": 1}
    ]


def test_the_order_moves_are_on_the_buyers_timeline(make_gadget: MakeGadget) -> None:
    lamp = make_gadget(price=Decimal("10.00"), stock=9)
    paid = pay(place(cart_with(("gadget", lamp, 1)), email="lea@example.com"))
    dropped = place(cart_with(("gadget", lamp, 1)), email="lea@example.com")
    services.cancel(dropped, reason="changed my mind")
    deliver_now()
    titles = list(
        TimelineEntry.objects.filter(person=paid.person_id)
        .order_by("occurred_at", "title")
        .values_list("kind", "title")
    )
    assert ("commerce.order.placed", f"Order {paid.number} placed") in titles
    assert ("commerce.order.paid", f"Order {paid.number} paid") in titles
    assert ("commerce.order.cancelled", f"Order {dropped.number} cancelled") in titles
    cancelled = TimelineEntry.objects.get(kind="commerce.order.cancelled")
    assert cancelled.body == "changed my mind"
    deliver_now()  # again: nothing is written twice
    assert TimelineEntry.objects.filter(person=paid.person_id).count() == len(titles)


def test_a_failed_payment_publishes_no_order_event_but_its_cancel_does(
    make_gadget: MakeGadget,
) -> None:
    lamp = make_gadget(stock=9)
    with capture_events() as published:
        order = pay(place(cart_with(("gadget", lamp, 1))), outcome="decline")
    assert order.status == "failed"
    published.assert_not_published("commerce.order.paid")
    with capture_events() as later:
        services.cancel(order)
    later.assert_published("commerce.order.cancelled", subject=order, reason="")
