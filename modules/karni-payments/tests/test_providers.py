"""Provider interface conformance (all three providers) + provider utilities.

The Stripe/Razorpay SDKs are mocked via ``sys.modules`` for the conformance
run; the real-SDK import tests use ``importorskip`` and only run where the
extras are installed.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from karni_payments.providers.base import (
    CheckoutSession,
    ParsedEvent,
    ParsedEventStatus,
    PaymentProvider,
    UnsupportedCurrencyError,
    WebhookVerificationError,
    from_minor_units,
    get_provider,
    get_provider_by_name,
    to_minor_units,
)
from karni_payments.providers.razorpay import EVENT_ID_HEADER, SIGNATURE_HEADER, RazorpayProvider
from karni_payments.providers.stripe import StripeProvider
from karni_payments.providers.test import TestProvider

GOOD_SIGNATURE = "good-signature"


# ---------------------------------------------------------------------------
# Fake SDKs
# ---------------------------------------------------------------------------


def _fake_stripe() -> ModuleType:
    module = ModuleType("stripe")

    class Webhook:
        @staticmethod
        def construct_event(payload: bytes, sig_header: str, secret: str) -> dict[str, Any]:
            if sig_header != GOOD_SIGNATURE:
                raise ValueError("bad stripe signature")
            return json.loads(payload)

    module.checkout = SimpleNamespace(  # type: ignore[attr-defined]
        Session=SimpleNamespace(
            create=lambda **kwargs: {"id": "cs_123", "url": "https://stripe.test/cs_123"}
        )
    )
    module.Refund = SimpleNamespace(create=lambda **kwargs: {"id": "re_123"})  # type: ignore[attr-defined]
    module.Webhook = Webhook  # type: ignore[attr-defined]
    return module


def _fake_razorpay() -> ModuleType:
    module = ModuleType("razorpay")

    class Client:
        def __init__(self, auth: tuple[str, str]) -> None:
            self.payment_link = SimpleNamespace(
                create=lambda data: {"id": "plink_1", "short_url": "https://rzp.test/plink_1"}
            )
            self.payment = SimpleNamespace(refund=lambda pid, data: {"id": "rfnd_1"})

    class Utility:
        def __init__(self, client: Any = None) -> None:
            self.client = client

        def verify_webhook_signature(self, body: str, signature: str, secret: str) -> None:
            if signature != GOOD_SIGNATURE:
                raise ValueError("bad razorpay signature")

    module.Client = Client  # type: ignore[attr-defined]
    module.Utility = Utility  # type: ignore[attr-defined]
    return module


@pytest.fixture
def fake_sdks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "stripe", _fake_stripe())
    monkeypatch.setitem(sys.modules, "razorpay", _fake_razorpay())


def _signed_webhook(
    provider: PaymentProvider, event: dict[str, Any]
) -> tuple[bytes, dict[str, str]]:
    """A valid (body, headers) delivery for each provider under the fakes."""
    if isinstance(provider, TestProvider):
        return TestProvider.build_webhook(event)
    body = json.dumps(event).encode()
    if isinstance(provider, StripeProvider):
        return body, {"Stripe-Signature": GOOD_SIGNATURE}
    return body, {SIGNATURE_HEADER: GOOD_SIGNATURE, EVENT_ID_HEADER: "rzp_evt_1"}


CREDENTIALS = {
    "STRIPE_SECRET_KEY": "sk_test",
    "STRIPE_WEBHOOK_SECRET": "whsec_test",
    "RAZORPAY_KEY_ID": "rzp_key",
    "RAZORPAY_KEY_SECRET": "rzp_secret",
    "RAZORPAY_WEBHOOK_SECRET": "rzp_whsec",
}


# ---------------------------------------------------------------------------
# Conformance: the same contract for all three providers
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("provider_class", [StripeProvider, RazorpayProvider, TestProvider])
class TestProviderConformance:
    @pytest.fixture(autouse=True)
    def _setup(self, fake_sdks: None) -> None:
        self._settings = override_settings(**CREDENTIALS)
        self._settings.enable()
        yield
        self._settings.disable()

    def test_declares_a_name(self, provider_class: type[PaymentProvider]) -> None:
        assert isinstance(provider_class.name, str) and provider_class.name

    def test_create_checkout_returns_session(
        self, provider_class: type[PaymentProvider], make_payment
    ) -> None:
        payment = make_payment(provider=provider_class.name)
        session = provider_class().create_checkout(
            payment, "http://localhost:5173/ok", "http://localhost:5173/no"
        )
        assert isinstance(session, CheckoutSession)
        assert session.id and session.url.startswith("https://")

    def test_create_refund_returns_provider_id(
        self, provider_class: type[PaymentProvider], make_payment
    ) -> None:
        payment = make_payment(provider=provider_class.name, provider_payment_id="pi_1")
        refund = payment.refunds.create(amount=Decimal("10.00"))
        refund_id = provider_class().create_refund(refund)
        assert isinstance(refund_id, str) and refund_id

    def test_parse_webhook_rejects_bad_signature(
        self, provider_class: type[PaymentProvider]
    ) -> None:
        body = json.dumps({"id": "evt", "type": "x"}).encode()
        headers = {
            "Stripe-Signature": "forged",
            SIGNATURE_HEADER: "forged",
            EVENT_ID_HEADER: "rzp_evt",
            TestProvider.signature_header: "forged",
        }
        with pytest.raises(WebhookVerificationError):
            provider_class().parse_webhook(body, headers)

    def test_parse_webhook_returns_parsed_event(
        self, provider_class: type[PaymentProvider]
    ) -> None:
        provider = provider_class()
        body, headers = _signed_webhook(provider, {"id": "evt_1", "type": "ignored.type"})
        parsed = provider.parse_webhook(body, headers)
        assert isinstance(parsed, ParsedEvent)
        assert parsed.event_id
        assert parsed.status is None or isinstance(parsed.status, ParsedEventStatus)
        assert parsed.raw  # the verbatim payload survives for re-processing

    def test_map_event_unknown_type_has_no_status(
        self, provider_class: type[PaymentProvider]
    ) -> None:
        parsed = provider_class().map_event("evt", "totally.unknown", {})
        assert parsed.status is None


# ---------------------------------------------------------------------------
# Per-provider event mapping tables (amendment G4)
# ---------------------------------------------------------------------------


def _stripe_event(event_type: str, obj: dict[str, Any]) -> dict[str, Any]:
    return {"id": "evt_1", "type": event_type, "data": {"object": obj}}


@pytest.mark.parametrize(
    ("event_type", "obj", "status", "payment_id", "session_id"),
    [
        (
            "checkout.session.completed",
            {"id": "cs_1", "payment_intent": "pi_1"},
            ParsedEventStatus.SUCCEEDED,
            "pi_1",
            "cs_1",
        ),
        (
            "checkout.session.expired",
            {"id": "cs_1", "payment_intent": None},
            ParsedEventStatus.EXPIRED,
            None,
            "cs_1",
        ),
        ("payment_intent.succeeded", {"id": "pi_1"}, ParsedEventStatus.SUCCEEDED, "pi_1", None),
        (
            "payment_intent.payment_failed",
            {"id": "pi_1"},
            ParsedEventStatus.FAILED,
            "pi_1",
            None,
        ),
        (
            "charge.refunded",
            {"id": "ch_1", "payment_intent": "pi_1"},
            ParsedEventStatus.REFUND_SUCCEEDED,
            "pi_1",
            None,
        ),
    ],
)
def test_stripe_event_mapping(
    event_type: str,
    obj: dict[str, Any],
    status: ParsedEventStatus,
    payment_id: str | None,
    session_id: str | None,
) -> None:
    parsed = StripeProvider().map_event("evt_1", event_type, _stripe_event(event_type, obj))
    assert parsed.status is status
    assert parsed.provider_payment_id == payment_id
    assert parsed.checkout_session_id == session_id


def test_razorpay_payment_link_paid_mapping() -> None:
    payload = {
        "event": "payment_link.paid",
        "payload": {
            "payment_link": {"entity": {"id": "plink_1"}},
            "payment": {"entity": {"id": "pay_1"}},
        },
    }
    parsed = RazorpayProvider().map_event("rzp_evt_1", "payment_link.paid", payload)
    assert parsed.status is ParsedEventStatus.SUCCEEDED
    assert parsed.checkout_session_id == "plink_1"
    assert parsed.provider_payment_id == "pay_1"


@pytest.mark.parametrize(
    ("event_type", "status"),
    [
        ("refund.processed", ParsedEventStatus.REFUND_SUCCEEDED),
        ("refund.failed", ParsedEventStatus.REFUND_FAILED),
    ],
)
def test_razorpay_refund_mapping(event_type: str, status: ParsedEventStatus) -> None:
    payload = {
        "event": event_type,
        "payload": {"refund": {"entity": {"id": "rfnd_1", "payment_id": "pay_1"}}},
    }
    parsed = RazorpayProvider().map_event("rzp_evt_1", event_type, payload)
    assert parsed.status is status
    assert parsed.provider_payment_id == "pay_1"


def test_razorpay_event_id_comes_from_header(fake_sdks: None) -> None:
    with override_settings(**CREDENTIALS):
        body = json.dumps({"event": "payment_link.paid", "payload": {}}).encode()
        parsed = RazorpayProvider().parse_webhook(
            body, {SIGNATURE_HEADER: GOOD_SIGNATURE, EVENT_ID_HEADER: "rzp_evt_42"}
        )
    assert parsed.event_id == "rzp_evt_42"


def test_razorpay_missing_event_id_header_is_a_verification_failure(fake_sdks: None) -> None:
    with override_settings(**CREDENTIALS):
        body = json.dumps({"event": "payment_link.paid"}).encode()
        with pytest.raises(WebhookVerificationError, match=EVENT_ID_HEADER):
            RazorpayProvider().parse_webhook(body, {SIGNATURE_HEADER: GOOD_SIGNATURE})


# ---------------------------------------------------------------------------
# Lazy SDK imports and lazy credentials
# ---------------------------------------------------------------------------


def test_stripe_sdk_missing_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "stripe", None)
    with (
        override_settings(STRIPE_SECRET_KEY="sk"),
        pytest.raises(ImproperlyConfigured, match=r"karni-payments\[stripe\]"),
    ):
        StripeProvider().parse_webhook(b"{}", {})


def test_razorpay_sdk_missing_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "razorpay", None)
    with (
        override_settings(
            RAZORPAY_KEY_ID="k", RAZORPAY_KEY_SECRET="s", RAZORPAY_WEBHOOK_SECRET="w"
        ),
        pytest.raises(ImproperlyConfigured, match=r"karni-payments\[razorpay\]"),
    ):
        RazorpayProvider().parse_webhook(b"{}", {EVENT_ID_HEADER: "e", SIGNATURE_HEADER: "s"})


def test_missing_stripe_credentials_fail_lazily(fake_sdks: None) -> None:
    # No boot-time failure: the error surfaces at use, naming the setting.
    with pytest.raises(ImproperlyConfigured, match="STRIPE_WEBHOOK_SECRET"):
        StripeProvider().parse_webhook(b"{}", {})


def test_real_stripe_sdk_importable_when_extra_installed() -> None:
    pytest.importorskip("stripe")
    import stripe  # noqa: F401


def test_real_razorpay_sdk_importable_when_extra_installed() -> None:
    pytest.importorskip("razorpay")
    import razorpay  # noqa: F401


# ---------------------------------------------------------------------------
# Minor units + zero-decimal table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "currency", "minor"),
    [
        (Decimal("10.50"), "usd", 1050),
        (Decimal("10.50"), "USD", 1050),
        (Decimal("0.01"), "eur", 1),
        (Decimal("500"), "jpy", 500),
        (Decimal("1250"), "krw", 1250),
    ],
)
def test_to_minor_units(amount: Decimal, currency: str, minor: int) -> None:
    assert to_minor_units(amount, currency) == minor


@pytest.mark.parametrize(
    ("minor", "currency", "amount"),
    [(1050, "usd", Decimal("10.50")), (500, "jpy", Decimal("500"))],
)
def test_from_minor_units(minor: int, currency: str, amount: Decimal) -> None:
    assert from_minor_units(minor, currency) == amount


def test_sub_minor_unit_precision_rejected() -> None:
    with pytest.raises(UnsupportedCurrencyError):
        to_minor_units(Decimal("10.5"), "jpy")


def test_three_decimal_currencies_unsupported() -> None:
    with pytest.raises(UnsupportedCurrencyError, match="3-decimal"):
        to_minor_units(Decimal("1.000"), "kwd")
    with pytest.raises(UnsupportedCurrencyError, match="3-decimal"):
        from_minor_units(1000, "bhd")


# ---------------------------------------------------------------------------
# Resolution, caching, reset
# ---------------------------------------------------------------------------


def test_get_provider_resolves_configured_shortcut() -> None:
    provider = get_provider()  # tests/settings.py sets "test"
    assert isinstance(provider, TestProvider)


def test_get_provider_caches_instances() -> None:
    assert get_provider() is get_provider()


def test_get_provider_accepts_dotted_path() -> None:
    with override_settings(KARNI_PAYMENTS_PROVIDER="karni_payments.providers.test.TestProvider"):
        assert isinstance(get_provider(), TestProvider)


def test_get_provider_cache_resets_on_setting_change() -> None:
    before = get_provider()
    with override_settings(KARNI_PAYMENTS_PROVIDER="test"):
        inside = get_provider()
        assert inside is not before  # the cache was dropped on setting_changed
    assert get_provider() is not inside  # and dropped again on exit


def test_get_provider_rejects_unimportable_spec() -> None:
    with override_settings(KARNI_PAYMENTS_PROVIDER="not.a.real.Provider"):
        with pytest.raises(ImproperlyConfigured, match="not.a.real.Provider"):
            get_provider()


def test_get_provider_rejects_non_provider_class() -> None:
    with override_settings(KARNI_PAYMENTS_PROVIDER="decimal.Decimal"):
        with pytest.raises(ImproperlyConfigured, match="PaymentProvider"):
            get_provider()


def test_get_provider_by_name_accepts_shortcuts_only() -> None:
    assert isinstance(get_provider_by_name("test"), TestProvider)
    with pytest.raises(LookupError):
        get_provider_by_name("karni_payments.providers.test.TestProvider")


def test_get_provider_by_name_accepts_the_configured_custom_name() -> None:
    with override_settings(KARNI_PAYMENTS_PROVIDER="karni_payments.providers.test.TestProvider"):
        assert isinstance(get_provider_by_name("test"), TestProvider)
