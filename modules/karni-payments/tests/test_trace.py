"""Development trace (karni.debug): a webhook delivery is linked to the checkout it settles."""

from __future__ import annotations

import io
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from django.core.management import call_command
from karni.debug import store
from karni.tracing import bound_request_id

from karni_payments import services

from .conftest import CANCEL_URL, SUCCESS_URL

pytestmark = pytest.mark.django_db


def test_the_webhook_and_its_checkout_are_linked(
    tmp_path: Path,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
    user: Any,
    deliver_webhook: Any,
    django_capture_on_commit_callbacks: Any,
) -> None:
    monkeypatch.setattr(store, "capture_root", lambda: tmp_path / ".karni")
    settings.DEBUG = True
    settings.ALLOWED_HOSTS = ["testserver"]
    with bound_request_id("checkout-req"):
        payment, session = services.create_checkout(
            user, amount=Decimal("10.00"), success_url=SUCCESS_URL, cancel_url=CANCEL_URL
        )
    with django_capture_on_commit_callbacks() as callbacks:
        response = deliver_webhook(
            {
                "id": "evt_9",
                "type": "checkout.completed",
                "status": "succeeded",
                "checkout_session_id": session.id,
            }
        )
    webhook_request = response["X-Request-ID"]
    # Outside a test the view's commit (and so the enqueue) happens inside the
    # request; the test transaction defers it, so replay that here.
    with bound_request_id(webhook_request):
        for callback in callbacks:
            callback()
    events = [event["event"] for event in store.iter_events({webhook_request})]
    assert events[:2] == ["request.start", "webhook.received"]
    assert "webhook.matched" in events and "task.succeeded" in events

    out = io.StringIO()
    call_command("karni_trace", webhook_request, "--json", stdout=out)
    linked = json.loads(out.getvalue())["linked"]
    assert [entry["request_id"] for entry in linked] == ["checkout-req"]
    assert linked[0]["refs"] == [f"karni_payments.Payment:{payment.pk}"]
