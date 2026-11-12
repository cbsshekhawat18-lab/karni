"""A succeeded payment lands on the payer's timeline when the payer is a known person."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.test import override_settings
from karni.accounts.permissions import assign_role
from karni.accounts.roles import sync_roles
from karni.people.models import Person
from karni.testing import capture_events, client_as, deliver_now
from karni.timeline.models import TimelineEntry, TimelineLink

from karni_payments.models import Payment, WebhookEvent
from karni_payments.services import apply_event

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _customer_role() -> Iterator[None]:
    with override_settings(KARNI_ROLES={"customer": {"grants": {"*": "own"}}}):
        sync_roles()
        yield


def _succeed(payment: Payment) -> None:
    webhook = WebhookEvent.objects.create(
        provider="test",
        event_id=f"evt_tl_{payment.pk}",
        event_type="test.event",
        payload={
            "id": f"evt_tl_{payment.pk}",
            "status": "succeeded",
            "payment_id": payment.provider_payment_id,
        },
    )
    apply_event(webhook)


def test_a_succeeded_payment_lands_on_the_payers_timeline(
    make_payment: Any, user: AbstractBaseUser
) -> None:
    person = Person.objects.create(email="buyer@example.com", user=user)
    payment = make_payment(provider_payment_id="pi_tl_1", amount=Decimal("42.50"))
    with capture_events() as published:
        _succeed(payment)
    published.assert_published("payments.payment.succeeded", person=person)
    deliver_now()
    entry = TimelineEntry.objects.get(kind="payments.payment.succeeded")
    assert entry.person == person and entry.source == "payments"
    assert entry.title == "Payment of 42.50 usd succeeded"
    link = TimelineLink.objects.get(entry=entry)
    assert (link.content_type.app_label, link.object_id) == ("karni_payments", str(payment.pk))

    assign_role(user, "customer")
    response = client_as(user=user).get("/api/timeline/", {"person": str(person.pk)})
    assert response.status_code == 200
    assert [row["title"] for row in response.data["results"]] == ["Payment of 42.50 usd succeeded"]


def test_a_payment_without_a_known_person_is_on_the_payments_timeline_only(
    make_payment: Any,
) -> None:
    payment = make_payment(provider_payment_id="pi_tl_2")
    with capture_events() as published:
        _succeed(payment)
    assert published.assert_published("payments.payment.succeeded").person is None
    deliver_now()
    # The payment is the subject, so the entry shows on the payment's timeline only.
    entry = TimelineEntry.objects.get(kind="payments.payment.succeeded")
    assert entry.person is None


def test_the_payer_of_another_payment_does_not_see_it(
    make_payment: Any, user: AbstractBaseUser, other_user: AbstractBaseUser
) -> None:
    payer = Person.objects.create(email="buyer@example.com", user=user)
    Person.objects.create(email="other@example.com", user=other_user)
    payment = make_payment(provider_payment_id="pi_tl_3")
    _succeed(payment)
    deliver_now()
    assign_role(other_user, "customer")
    ref = f"karni_payments.payment:{payment.pk}"
    other = client_as(user=other_user)
    assert other.get("/api/timeline/", {"subject": ref}).status_code == 404
    assert other.get("/api/timeline/", {"person": str(payer.pk)}).status_code == 404
