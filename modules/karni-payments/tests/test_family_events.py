"""karni-payments publishes its family events through the bus (karni_payments/listeners.py)."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from itertools import count
from typing import Any

import pytest
from karni.events import Event, subscribe
from karni.outbox.bus import registry
from karni.outbox.models import Delivery, OutboxEvent
from karni.testing import assert_events_declared, capture_events, deliver_now

from karni_payments.models import Payment, Refund, WebhookEvent
from karni_payments.services import apply_event

pytestmark = pytest.mark.django_db

_ids = count(1)


def _webhook(status: str, payment_id: str) -> WebhookEvent:
    event_id = f"evt_bus_{next(_ids)}"
    return WebhookEvent.objects.create(
        provider="test",
        event_id=event_id,
        event_type="test.event",
        payload={"id": event_id, "status": status, "payment_id": payment_id},
    )


@pytest.fixture
def received() -> Iterator[list[Event]]:
    """A subscriber to payments.payment.succeeded, for one test."""
    found: list[Event] = []
    subscribe("payments.payment.succeeded", name="tests.payments.received")(found.append)
    yield found
    registry.remove_subscriber("tests.payments.received")


def test_payments_declares_what_it_publishes() -> None:
    assert assert_events_declared("karni_payments") == [
        "payments.payment.failed",
        "payments.payment.succeeded",
        "payments.refund.succeeded",
    ]


def test_a_succeeded_webhook_publishes_payment_succeeded(make_payment: Any) -> None:
    payment = make_payment(provider_payment_id="pi_1", amount=Decimal("42.50"))
    with capture_events() as published:
        apply_event(_webhook("succeeded", "pi_1"))
    event = published.assert_published(
        "payments.payment.succeeded",
        count=1,
        subject=payment,
        payment=str(payment.pk),
        amount="42.50",
        currency="usd",
    )
    assert event.person is None
    assert OutboxEvent.objects.filter(name="payments.payment.succeeded").count() == 1


def test_a_failed_webhook_publishes_payment_failed(make_payment: Any) -> None:
    payment = make_payment(provider_payment_id="pi_2")
    with capture_events() as published:
        apply_event(_webhook("failed", "pi_2"))
    published.assert_published("payments.payment.failed", payment=str(payment.pk))
    published.assert_not_published("payments.payment.succeeded")


def test_a_save_that_keeps_the_status_publishes_nothing(make_payment: Any) -> None:
    with capture_events() as published:
        payment = make_payment(provider_payment_id="pi_3")  # created pending
        payment.metadata = {"note": "x"}
        payment.save()
        apply_event(_webhook("processing", "pi_3"))
    assert len(published) == 0
    with capture_events() as published:
        apply_event(_webhook("succeeded", "pi_3"))
        apply_event(_webhook("succeeded", "pi_3"))  # a duplicate is a no-op note
    published.assert_published("payments.payment.succeeded", count=1)


def test_a_refund_that_goes_through_publishes_refund_succeeded(make_payment: Any) -> None:
    payment = make_payment(status=Payment.Status.SUCCEEDED, provider_payment_id="pi_4")
    refund = Refund.objects.create(payment=payment, amount=Decimal("10.00"))
    with capture_events() as published:
        apply_event(_webhook("refund_succeeded", "pi_4"))
    published.assert_published(
        "payments.refund.succeeded",
        subject=refund,
        refund=str(refund.pk),
        payment=str(payment.pk),
        amount="10.00",
    )


def test_a_subscriber_receives_the_payment_after_delivery(
    make_payment: Any, received: list[Event]
) -> None:
    payment = make_payment(provider_payment_id="pi_5")
    apply_event(_webhook("succeeded", "pi_5"))
    assert Delivery.objects.get(subscriber="tests.payments.received").status == "pending"
    deliver_now()
    [event] = received
    assert (event.name, event["payment"], event["amount"]) == (
        "payments.payment.succeeded",
        str(payment.pk),
        "100.00",
    )
    assert event.subject == {"model": "karni_payments.payment", "id": str(payment.pk)}
