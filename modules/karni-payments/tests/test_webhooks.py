"""The webhook view pipeline (amendment G3): verify → persist → enqueue.

Enqueueing happens via ``transaction.on_commit``, so these tests use
pytest-django's ``django_capture_on_commit_callbacks`` together with eager
Celery to run the task exactly when a real commit would.
"""

from __future__ import annotations

import json

import pytest

from karni_payments.models import Payment, WebhookEvent
from karni_payments.providers.test import TestProvider

pytestmark = pytest.mark.django_db


def test_bad_signature_is_400_and_unpersisted(client, caplog) -> None:
    body = json.dumps({"id": "evt_1", "type": "x"}).encode()
    with caplog.at_level("WARNING", logger="karni_payments.webhooks"):
        response = client.post(
            "/payments/webhook/test/",
            data=body,
            content_type="application/json",
            headers={TestProvider.signature_header: "forged"},
        )
    assert response.status_code == 400
    assert WebhookEvent.objects.count() == 0
    # Exactly one structured warning from the module, carrying provider + IP.
    [record] = [r for r in caplog.records if r.name == "karni_payments.webhooks"]
    assert "provider=test" in record.getMessage()
    assert "ip=" in record.getMessage()
    assert "signature" in record.getMessage()


def test_missing_event_id_is_400_and_unpersisted(client, deliver_webhook) -> None:
    response = deliver_webhook({"type": "x"})  # signed, but no id
    assert response.status_code == 400
    assert WebhookEvent.objects.count() == 0


def test_unknown_provider_404(client) -> None:
    response = client.post(
        "/payments/webhook/nonsense/", data=b"{}", content_type="application/json"
    )
    assert response.status_code == 404


def test_get_is_not_allowed(client) -> None:
    assert client.get("/payments/webhook/test/").status_code == 405


def test_first_delivery_persists_enqueues_and_processes(
    deliver_webhook, make_payment, django_capture_on_commit_callbacks
) -> None:
    payment = make_payment(provider_payment_id="pi_1")
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        response = deliver_webhook(
            {
                "id": "evt_1",
                "type": "payment.succeeded",
                "status": "succeeded",
                "payment_id": "pi_1",
            }
        )
    assert response.status_code == 200
    assert len(callbacks) == 1  # exactly one enqueue, after commit
    event = WebhookEvent.objects.get()
    assert event.provider == "test" and event.event_id == "evt_1"
    assert event.processed_at is not None
    payment.refresh_from_db()
    assert payment.status == Payment.Status.SUCCEEDED


def test_duplicate_of_processed_event_is_a_noop(
    deliver_webhook, make_payment, django_capture_on_commit_callbacks
) -> None:
    make_payment(provider_payment_id="pi_1")
    event = {
        "id": "evt_1",
        "type": "payment.succeeded",
        "status": "succeeded",
        "payment_id": "pi_1",
    }
    with django_capture_on_commit_callbacks(execute=True):
        deliver_webhook(event)
    with django_capture_on_commit_callbacks(execute=True) as second:
        response = deliver_webhook(event)
    assert response.status_code == 200
    assert second == []  # processed → no re-enqueue
    assert WebhookEvent.objects.count() == 1


def test_duplicate_with_null_processed_at_is_reenqueued(
    deliver_webhook, make_payment, django_capture_on_commit_callbacks
) -> None:
    """Redelivery recovers an event whose first task run never completed."""
    payment = make_payment(provider_payment_id="pi_1")
    event = {
        "id": "evt_1",
        "type": "payment.succeeded",
        "status": "succeeded",
        "payment_id": "pi_1",
    }
    with django_capture_on_commit_callbacks(execute=False) as dropped:
        deliver_webhook(event)
    assert len(dropped) == 1  # enqueued but (simulated) lost
    stored = WebhookEvent.objects.get()
    assert stored.processed_at is None

    with django_capture_on_commit_callbacks(execute=True) as retried:
        response = deliver_webhook(event)
    assert response.status_code == 200
    assert len(retried) == 1  # re-enqueued despite being a duplicate
    stored.refresh_from_db()
    assert stored.processed_at is not None
    payment.refresh_from_db()
    assert payment.status == Payment.Status.SUCCEEDED
