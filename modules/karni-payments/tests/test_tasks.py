"""The webhook task: idempotency, one-transaction stamping, error survival.

sqlite caveat (amendment G3): ``select_for_update`` is a no-op on sqlite,
which serialises writers anyway — these tests assert the task's *behaviour*
(skip-if-processed, stamp-with-state, error text survives rollback), not
genuine lock concurrency; that guarantee holds on PostgreSQL.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.test import override_settings
from django.utils import timezone

from karni_payments.models import Payment, WebhookEvent
from karni_payments.services import UnmatchedWebhookEventError
from karni_payments.tasks import process_webhook_event

pytestmark = pytest.mark.django_db

HANDLED: list[str] = []


def recording_handler(event: WebhookEvent) -> None:
    """A swapped-in KARNI_PAYMENTS_EVENT_HANDLER (amendment G8)."""
    HANDLED.append(event.event_id)


def _event(**payload_extra: Any) -> WebhookEvent:
    payload = {"id": "evt_t1", "type": "payment.succeeded", **payload_extra}
    return WebhookEvent.objects.create(
        provider="test",
        event_id=payload["id"],
        event_type=str(payload["type"]),
        payload=payload,
    )


def test_processed_event_is_skipped(make_payment) -> None:
    payment = make_payment(provider_payment_id="pi_1")
    event = _event(status="succeeded", payment_id="pi_1")
    event.processed_at = timezone.now()
    event.save(update_fields=["processed_at"])
    process_webhook_event(str(event.pk))
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PENDING  # nothing re-applied


def test_success_stamps_processed_at_with_the_state_change(make_payment) -> None:
    payment = make_payment(provider_payment_id="pi_1")
    event = _event(status="succeeded", payment_id="pi_1")
    process_webhook_event(str(event.pk))
    event.refresh_from_db()
    payment.refresh_from_db()
    assert event.processed_at is not None
    assert payment.status == Payment.Status.SUCCEEDED


def test_noop_note_is_persisted_alongside_the_stamp(make_payment) -> None:
    make_payment(provider_payment_id="pi_1", status=Payment.Status.SUCCEEDED)
    event = _event(status="succeeded", payment_id="pi_1")
    process_webhook_event(str(event.pk))
    event.refresh_from_db()
    assert event.processed_at is not None
    assert event.error.startswith("no-op:")


def test_unmatched_payment_raises_and_error_text_survives(db: None) -> None:
    event = _event(status="succeeded", payment_id="pi_ghost")
    with pytest.raises(UnmatchedWebhookEventError):
        process_webhook_event(str(event.pk))
    event.refresh_from_db()
    # Error text was written OUTSIDE the rolled-back transaction...
    assert "UnmatchedWebhookEventError" in event.error
    # ...and the event is NOT marked processed, so a retry can succeed.
    assert event.processed_at is None


def test_retry_after_failure_succeeds_once_the_payment_exists(make_payment) -> None:
    event = _event(status="succeeded", payment_id="pi_late")
    with pytest.raises(UnmatchedWebhookEventError):
        process_webhook_event(str(event.pk))
    payment = make_payment(provider_payment_id="pi_late")
    process_webhook_event(str(event.pk))  # the "retry"
    event.refresh_from_db()
    payment.refresh_from_db()
    assert event.processed_at is not None
    assert payment.status == Payment.Status.SUCCEEDED


def test_event_handler_setting_is_the_escape_hatch(make_payment) -> None:
    payment = make_payment(provider_payment_id="pi_1")
    event = _event(status="succeeded", payment_id="pi_1")
    HANDLED.clear()
    with override_settings(KARNI_PAYMENTS_EVENT_HANDLER="tests.test_tasks.recording_handler"):
        process_webhook_event(str(event.pk))
    assert HANDLED == [event.event_id]
    event.refresh_from_db()
    payment.refresh_from_db()
    assert event.processed_at is not None  # the task still stamps
    assert payment.status == Payment.Status.PENDING  # default machine replaced


def test_task_has_retry_policy() -> None:
    assert process_webhook_event.max_retries == 3
    assert Exception in process_webhook_event.autoretry_for
    assert process_webhook_event.retry_backoff
