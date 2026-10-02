"""The apply_event state machine: monotonic transitions, refunds, matching."""

from __future__ import annotations

from decimal import Decimal
from itertools import count
from typing import Any

import pytest

from karni_payments.models import Payment, Refund, WebhookEvent
from karni_payments.services import UnmatchedWebhookEventError, apply_event

pytestmark = pytest.mark.django_db

_event_ids = count(1)


def make_event(
    *,
    status: str | None = None,
    payment_id: str | None = None,
    checkout_session_id: str | None = None,
    event_type: str = "test.event",
) -> WebhookEvent:
    """Store a TestProvider-shaped WebhookEvent row."""
    event_id = f"evt_{next(_event_ids)}"
    payload: dict[str, Any] = {"id": event_id, "type": event_type}
    if status is not None:
        payload["status"] = status
    if payment_id is not None:
        payload["payment_id"] = payment_id
    if checkout_session_id is not None:
        payload["checkout_session_id"] = checkout_session_id
    return WebhookEvent.objects.create(
        provider="test", event_id=event_id, event_type=event_type, payload=payload
    )


# ---------------------------------------------------------------------------
# Payment transitions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("event_status", "target"),
    [
        ("processing", Payment.Status.PROCESSING),
        ("succeeded", Payment.Status.SUCCEEDED),
        ("failed", Payment.Status.FAILED),
        ("canceled", Payment.Status.CANCELED),
        ("expired", Payment.Status.CANCELED),  # expired sessions map to canceled
    ],
)
def test_pending_payment_advances(make_payment, event_status: str, target: str) -> None:
    payment = make_payment(provider_payment_id="pi_1")
    apply_event(make_event(status=event_status, payment_id="pi_1"))
    payment.refresh_from_db()
    assert payment.status == target


def test_terminal_states_never_regress(make_payment) -> None:
    payment = make_payment(status=Payment.Status.SUCCEEDED, provider_payment_id="pi_1")
    event = make_event(status="processing", payment_id="pi_1")
    apply_event(event)
    payment.refresh_from_db()
    event.refresh_from_db()
    assert payment.status == Payment.Status.SUCCEEDED
    assert event.error.startswith("no-op:")


def test_canceled_payment_ignores_late_success(make_payment) -> None:
    payment = make_payment(status=Payment.Status.CANCELED, provider_payment_id="pi_1")
    event = make_event(status="succeeded", payment_id="pi_1")
    apply_event(event)
    payment.refresh_from_db()
    event.refresh_from_db()
    assert payment.status == Payment.Status.CANCELED
    assert "would regress" in event.error


def test_same_status_event_is_a_noted_noop(make_payment) -> None:
    payment = make_payment(status=Payment.Status.SUCCEEDED, provider_payment_id="pi_1")
    event = make_event(status="succeeded", payment_id="pi_1")
    apply_event(event)
    event.refresh_from_db()
    assert "already succeeded" in event.error
    payment.refresh_from_db()
    assert payment.status == Payment.Status.SUCCEEDED


def test_unknown_event_type_is_a_noted_noop(make_payment) -> None:
    payment = make_payment(provider_payment_id="pi_1")
    event = make_event(payment_id="pi_1", event_type="totally.unknown")  # no status
    apply_event(event)
    event.refresh_from_db()
    assert "unhandled event type" in event.error
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PENDING


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def test_unmatched_payment_raises(db: None) -> None:
    with pytest.raises(UnmatchedWebhookEventError):
        apply_event(make_event(status="succeeded", payment_id="pi_ghost"))


def test_checkout_session_match_stamps_the_provider_payment_id(make_payment) -> None:
    payment = make_payment(checkout_session_id="test_cs_9")
    apply_event(
        make_event(status="succeeded", payment_id="pi_late", checkout_session_id="test_cs_9")
    )
    payment.refresh_from_db()
    assert payment.status == Payment.Status.SUCCEEDED
    assert payment.provider_payment_id == "pi_late"


def test_match_scoped_to_the_event_provider(make_payment) -> None:
    make_payment(provider="stripe", provider_payment_id="pi_1")
    with pytest.raises(UnmatchedWebhookEventError):
        apply_event(make_event(status="succeeded", payment_id="pi_1"))  # provider "test"


# ---------------------------------------------------------------------------
# Refund accounting through events
# ---------------------------------------------------------------------------


def test_full_refund_succeeded_event(make_payment) -> None:
    payment = make_payment(status=Payment.Status.SUCCEEDED, provider_payment_id="pi_1")
    refund = payment.refunds.create(amount=Decimal("100.00"))
    apply_event(make_event(status="refund_succeeded", payment_id="pi_1"))
    payment.refresh_from_db()
    refund.refresh_from_db()
    assert refund.status == Refund.Status.SUCCEEDED
    assert payment.status == Payment.Status.REFUNDED


def test_partial_refund_then_final_refund(make_payment) -> None:
    payment = make_payment(status=Payment.Status.SUCCEEDED, provider_payment_id="pi_1")
    payment.refunds.create(amount=Decimal("30.00"))
    apply_event(make_event(status="refund_succeeded", payment_id="pi_1"))
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PARTIALLY_REFUNDED

    payment.refunds.create(amount=Decimal("70.00"))
    apply_event(make_event(status="refund_succeeded", payment_id="pi_1"))
    payment.refresh_from_db()
    assert payment.status == Payment.Status.REFUNDED
    assert payment.refunds.filter(status=Refund.Status.SUCCEEDED).count() == 2


def test_refund_failed_event(make_payment) -> None:
    payment = make_payment(status=Payment.Status.SUCCEEDED, provider_payment_id="pi_1")
    refund = payment.refunds.create(amount=Decimal("40.00"))
    apply_event(make_event(status="refund_failed", payment_id="pi_1"))
    payment.refresh_from_db()
    refund.refresh_from_db()
    assert refund.status == Refund.Status.FAILED
    assert payment.status == Payment.Status.SUCCEEDED  # unchanged


def test_refund_event_without_local_refunds_is_a_noted_noop(make_payment) -> None:
    payment = make_payment(status=Payment.Status.SUCCEEDED, provider_payment_id="pi_1")
    event = make_event(status="refund_succeeded", payment_id="pi_1")
    apply_event(event)
    event.refresh_from_db()
    payment.refresh_from_db()
    assert "no-op" in event.error
    assert payment.status == Payment.Status.SUCCEEDED


def test_reapplying_a_refund_event_is_idempotent(make_payment) -> None:
    payment = make_payment(status=Payment.Status.SUCCEEDED, provider_payment_id="pi_1")
    payment.refunds.create(amount=Decimal("100.00"))
    event = make_event(status="refund_succeeded", payment_id="pi_1")
    apply_event(event)
    apply_event(event)  # second application finds everything already advanced
    payment.refresh_from_db()
    assert payment.status == Payment.Status.REFUNDED
    assert payment.refunds.filter(status=Refund.Status.SUCCEEDED).count() == 1
