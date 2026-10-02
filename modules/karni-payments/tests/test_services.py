"""Checkout and refund services: validator hook, redirect origins, accounting."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.test import override_settings
from rest_framework.exceptions import ValidationError

from karni_payments import services
from karni_payments.models import Payment, Refund
from karni_payments.providers.test import TestProvider
from tests.conftest import CANCEL_URL, SUCCESS_URL

pytestmark = pytest.mark.django_db


def rejecting_validator(
    *, user: Any, amount: Decimal, currency: str, metadata: dict[str, Any]
) -> None:
    """A checkout validator enforcing server-side pricing (used via settings)."""
    raise ValidationError({"amount": ["price disagreement"]})


class FailingCheckoutProvider(TestProvider):
    name = "test"

    def create_checkout(self, payment: Any, success_url: str, cancel_url: str) -> Any:
        raise RuntimeError("gateway down")


class FailingRefundProvider(TestProvider):
    name = "test"

    def create_refund(self, refund: Any) -> str:
        raise RuntimeError("gateway down")


# ---------------------------------------------------------------------------
# create_checkout
# ---------------------------------------------------------------------------


def test_create_checkout_happy_path(user) -> None:
    payment, session = services.create_checkout(
        user,
        amount=Decimal("42.00"),
        success_url=SUCCESS_URL,
        cancel_url=CANCEL_URL,
        metadata={"sku": "widget"},
    )
    assert payment.status == Payment.Status.PENDING
    assert payment.provider == "test"
    assert payment.currency == "usd"  # KARNI_PAYMENTS_CURRENCY default
    assert payment.user == user
    assert payment.metadata == {"sku": "widget"}
    assert payment.checkout_session_id == session.id == "test_cs_1"
    assert session.url.startswith("https://checkout.test/")


def test_create_checkout_explicit_currency_lowercased(user) -> None:
    payment, _session = services.create_checkout(
        user,
        amount=Decimal("500"),
        currency="JPY",
        success_url=SUCCESS_URL,
        cancel_url=CANCEL_URL,
    )
    assert payment.currency == "jpy"


def test_create_checkout_rejects_non_positive_amount(user) -> None:
    with pytest.raises(ValidationError):
        services.create_checkout(
            user, amount=Decimal("0"), success_url=SUCCESS_URL, cancel_url=CANCEL_URL
        )
    assert Payment.objects.count() == 0


def test_validator_hook_runs_before_payment_creation(user) -> None:
    with override_settings(
        KARNI_PAYMENTS_CHECKOUT_VALIDATOR="tests.test_services.rejecting_validator"
    ):
        with pytest.raises(ValidationError, match="price disagreement"):
            services.create_checkout(
                user, amount=Decimal("42.00"), success_url=SUCCESS_URL, cancel_url=CANCEL_URL
            )
    assert Payment.objects.count() == 0  # rejected BEFORE any row existed


@pytest.mark.parametrize(
    "bad_url",
    [
        "https://evil.example/win",
        "http://localhost:9999/elsewhere",  # same host, different port = different origin
        "not-a-url",
        "//localhost:5173/schemeless",
    ],
)
def test_redirect_urls_must_match_an_allowed_origin(user, bad_url: str) -> None:
    with pytest.raises(ValidationError):
        services.create_checkout(
            user, amount=Decimal("10.00"), success_url=bad_url, cancel_url=CANCEL_URL
        )
    assert Payment.objects.count() == 0


def test_allowed_redirects_setting_extends_origins(user) -> None:
    with override_settings(KARNI_PAYMENTS_ALLOWED_REDIRECTS=["https://shop.example"]):
        payment, _session = services.create_checkout(
            user,
            amount=Decimal("10.00"),
            success_url="https://shop.example/thanks",
            cancel_url=CANCEL_URL,
        )
    assert payment.checkout_session_id


def test_provider_failure_marks_payment_failed_and_reraises(user) -> None:
    with override_settings(KARNI_PAYMENTS_PROVIDER="tests.test_services.FailingCheckoutProvider"):
        with pytest.raises(RuntimeError, match="gateway down"):
            services.create_checkout(
                user, amount=Decimal("10.00"), success_url=SUCCESS_URL, cancel_url=CANCEL_URL
            )
    payment = Payment.objects.get()
    assert payment.status == Payment.Status.FAILED


# ---------------------------------------------------------------------------
# create_refund (amendment G5 — locked accounting)
# ---------------------------------------------------------------------------


def test_full_refund_by_default(make_payment) -> None:
    payment = make_payment(status=Payment.Status.SUCCEEDED, provider_payment_id="pi_1")
    refund = services.create_refund(payment)
    assert refund.amount == Decimal("100.00")
    assert refund.status == Refund.Status.PENDING
    assert refund.provider_refund_id == "test_re_1"


def test_partial_refund_with_reason(make_payment) -> None:
    payment = make_payment(status=Payment.Status.SUCCEEDED, provider_payment_id="pi_1")
    refund = services.create_refund(payment, Decimal("30.00"), reason="damaged item")
    assert refund.amount == Decimal("30.00")
    assert refund.reason == "damaged item"


def test_over_refund_rejected(make_payment) -> None:
    payment = make_payment(status=Payment.Status.SUCCEEDED)
    with pytest.raises(ValidationError, match="remainder"):
        services.create_refund(payment, Decimal("100.01"))
    assert payment.refunds.count() == 0


def test_remainder_counts_pending_and_succeeded_refunds(make_payment) -> None:
    payment = make_payment(status=Payment.Status.SUCCEEDED)
    payment.refunds.create(amount=Decimal("30.00"), status=Refund.Status.PENDING)
    payment.refunds.create(amount=Decimal("20.00"), status=Refund.Status.SUCCEEDED)
    with pytest.raises(ValidationError, match="remainder"):
        services.create_refund(payment, Decimal("60.00"))  # only 50 left
    refund = services.create_refund(payment)  # full remainder = 50
    assert refund.amount == Decimal("50.00")


def test_failed_refunds_do_not_count_toward_the_remainder(make_payment) -> None:
    payment = make_payment(status=Payment.Status.SUCCEEDED)
    payment.refunds.create(amount=Decimal("100.00"), status=Refund.Status.FAILED)
    refund = services.create_refund(payment)
    assert refund.amount == Decimal("100.00")


def test_nothing_left_to_refund_rejected(make_payment) -> None:
    payment = make_payment(status=Payment.Status.REFUNDED)
    payment.refunds.create(amount=Decimal("100.00"), status=Refund.Status.SUCCEEDED)
    with pytest.raises(ValidationError, match="[Nn]othing left"):
        services.create_refund(payment)


def test_non_positive_refund_amount_rejected(make_payment) -> None:
    payment = make_payment(status=Payment.Status.SUCCEEDED)
    with pytest.raises(ValidationError):
        services.create_refund(payment, Decimal("-1.00"))


def test_refund_provider_failure_marks_refund_failed_and_reraises(make_payment) -> None:
    payment = make_payment(status=Payment.Status.SUCCEEDED)
    with override_settings(KARNI_PAYMENTS_PROVIDER="tests.test_services.FailingRefundProvider"):
        with pytest.raises(RuntimeError, match="gateway down"):
            services.create_refund(payment)
    refund = payment.refunds.get()
    assert refund.status == Refund.Status.FAILED
    # The failed attempt does not count toward the remainder, so a retry
    # (back on the working provider) can still refund in full.
    retried = services.create_refund(payment)
    assert retried.amount == Decimal("100.00")
