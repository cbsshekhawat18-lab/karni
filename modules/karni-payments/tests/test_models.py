"""Model constraints and APIMeta exposure."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from karni.api.serializers import build_serializer

from karni_payments.models import Payment, Refund, WebhookEvent

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------


def test_webhook_event_dedupe_constraint() -> None:
    WebhookEvent.objects.create(provider="test", event_id="evt_1", event_type="x")
    with pytest.raises(IntegrityError), transaction.atomic():
        WebhookEvent.objects.create(provider="test", event_id="evt_1", event_type="y")


def test_same_event_id_allowed_across_providers() -> None:
    WebhookEvent.objects.create(provider="test", event_id="evt_1", event_type="x")
    WebhookEvent.objects.create(provider="stripe", event_id="evt_1", event_type="x")
    assert WebhookEvent.objects.count() == 2


def test_provider_payment_id_unique_when_set(make_payment) -> None:
    make_payment(provider_payment_id="pi_1")
    with pytest.raises(IntegrityError), transaction.atomic():
        make_payment(provider_payment_id="pi_1")


def test_blank_provider_payment_ids_may_repeat(make_payment) -> None:
    make_payment()
    make_payment()
    assert Payment.objects.filter(provider_payment_id="").count() == 2


def test_soft_deleting_a_payment_keeps_its_refunds(make_payment) -> None:
    payment = make_payment()
    Refund.objects.create(payment=payment, amount=Decimal("10.00"))
    payment.delete()
    assert Refund.objects.count() == 1
    assert Refund.objects.get().payment == payment  # FK still resolves


def test_refund_cascades_with_payment_hard_delete(make_payment) -> None:
    payment = make_payment()
    Refund.objects.create(payment=payment, amount=Decimal("10.00"))
    payment.hard_delete()
    assert Refund.objects.all_with_deleted().count() == 0


# ---------------------------------------------------------------------------
# APIMeta exposure (drives the generated serializers)
# ---------------------------------------------------------------------------


def test_payment_serializer_excludes_checkout_internals() -> None:
    fields = build_serializer(Payment)().fields
    assert "checkout_session_id" not in fields
    for expected in ("amount", "currency", "status", "provider", "user", "metadata"):
        assert expected in fields


def test_payment_serializer_read_only_fields() -> None:
    fields = build_serializer(Payment)().fields
    for name in ("status", "provider", "provider_payment_id", "id", "created_at"):
        assert fields[name].read_only, name
    assert not fields["amount"].read_only


def test_refund_serializer_is_fully_read_only_except_audit_defaults() -> None:
    fields = build_serializer(Refund)().fields
    for name in ("payment", "amount", "status", "provider_refund_id", "reason"):
        assert fields[name].read_only, name
