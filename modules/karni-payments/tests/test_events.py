"""karni_payments.events (experimental): payment and refund signals."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from karni_payments.events import payment_status_changed, refund_created, refund_status_changed
from karni_payments.models import Payment, Refund
from karni_payments.services import create_refund
from karni_payments.test_checkout import settle

pytestmark = pytest.mark.django_db


@pytest.fixture
def heard() -> Iterator[list[tuple[str, dict[str, Any]]]]:
    found: list[tuple[str, dict[str, Any]]] = []

    def payment(sender: Any, **kwargs: Any) -> None:
        found.append(("payment", kwargs))

    def created(sender: Any, **kwargs: Any) -> None:
        found.append(("refund_created", kwargs))

    def refund(sender: Any, **kwargs: Any) -> None:
        found.append(("refund", kwargs))

    payment_status_changed.connect(payment)
    refund_created.connect(created)
    refund_status_changed.connect(refund)
    yield found
    payment_status_changed.disconnect(payment)
    refund_created.disconnect(created)
    refund_status_changed.disconnect(refund)


def test_a_settled_payment_is_announced_with_its_move(make_payment, heard) -> None:
    payment = make_payment(checkout_session_id="test_cs_1", provider="test")
    settle(payment, "pay")
    [(kind, values)] = heard
    assert kind == "payment"
    assert (values["source"], values["target"]) == ("pending", "succeeded")
    assert values["payment"].pk == payment.pk


def test_a_refund_is_announced_when_asked_for_and_when_it_settles(
    make_payment, deliver_webhook, django_capture_on_commit_callbacks, heard
) -> None:
    payment = make_payment(status=Payment.Status.SUCCEEDED, provider_payment_id="pi_9")
    refund = create_refund(payment)
    assert heard[-1][0] == "refund_created"
    assert heard[-1][1]["refund"].pk == refund.pk
    with django_capture_on_commit_callbacks(execute=True):
        deliver_webhook(
            {"id": "evt_r", "type": "refund", "status": "refund_succeeded", "payment_id": "pi_9"}
        )
    kinds = [kind for kind, _ in heard]
    assert kinds == ["refund_created", "refund", "payment"]
    assert heard[1][1]["target"] == Refund.Status.SUCCEEDED
    assert (heard[2][1]["source"], heard[2][1]["target"]) == ("succeeded", "refunded")
