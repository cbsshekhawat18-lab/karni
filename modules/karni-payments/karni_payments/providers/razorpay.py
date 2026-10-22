"""Razorpay provider: Payment Links, refunds, signed webhooks.

Razorpay's hosted checkout here is **Payment Links** (amendment G4): a
``payment_link.create`` call returns an id plus a ``short_url`` the customer
is redirected to — that pair is this provider's
:class:`~karni_payments.providers.base.CheckoutSession`.

The ``razorpay`` SDK is imported lazily so the module imports without the
extra installed; the first real use raises an install hint
(``pip install "karni-payments[razorpay]"``). Credentials
(``RAZORPAY_KEY_ID`` / ``RAZORPAY_KEY_SECRET`` / ``RAZORPAY_WEBHOOK_SECRET``)
are read per call and validated lazily.

Webhook identity: Razorpay carries the delivery id in the
``X-Razorpay-Event-Id`` **header** (not the body) — a missing header is a
verification failure.

Native event → :class:`ParsedEventStatus` mapping (amendment G4):

======================  ====================
``payment_link.paid``   ``succeeded``
``refund.processed``    ``refund_succeeded``
``refund.failed``       ``refund_failed``
anything else           ``None`` (no-op)
======================  ====================

Override / escape hatch: subclass and extend ``EVENT_STATUS`` (or override
:meth:`map_event`), then point ``KARNI_PAYMENTS_PROVIDER`` at your subclass.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar

from karni.exceptions import KarniImproperlyConfigured

from karni_payments import conf
from karni_payments.providers.base import (
    CheckoutSession,
    ParsedEvent,
    ParsedEventStatus,
    PaymentProvider,
    WebhookVerificationError,
    to_minor_units,
)

if TYPE_CHECKING:
    from karni_payments.models import Payment, Refund

__all__ = ["RazorpayProvider"]

EVENT_ID_HEADER = "X-Razorpay-Event-Id"
SIGNATURE_HEADER = "X-Razorpay-Signature"


def _razorpay_sdk() -> Any:
    """Import the ``razorpay`` SDK lazily, with an install hint on failure."""
    try:
        import razorpay
    except ImportError as exc:
        raise KarniImproperlyConfigured(
            "The Razorpay provider needs the razorpay SDK. Install the extra: "
            'pip install "karni-payments[razorpay]".',
            code="PAY003",
        ) from exc
    return razorpay


class RazorpayProvider(PaymentProvider):
    """Razorpay gateway adapter (Payment Links)."""

    name: ClassVar[str] = "razorpay"

    EVENT_STATUS: ClassVar[dict[str, ParsedEventStatus]] = {
        "payment_link.paid": ParsedEventStatus.SUCCEEDED,
        "refund.processed": ParsedEventStatus.REFUND_SUCCEEDED,
        "refund.failed": ParsedEventStatus.REFUND_FAILED,
    }

    def _client(self) -> Any:
        key_id = str(conf.get("RAZORPAY_KEY_ID"))
        key_secret = str(conf.get("RAZORPAY_KEY_SECRET"))
        if not key_id or not key_secret:
            raise KarniImproperlyConfigured(
                "RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are not set, so the Razorpay "
                "provider cannot make API calls. Set both in the environment (.env in "
                "development), or use KARNI_PAYMENTS_PROVIDER = 'test' locally.",
                code="PAY004",
            )
        return _razorpay_sdk().Client(auth=(key_id, key_secret))

    def create_checkout(
        self, payment: Payment, success_url: str, cancel_url: str
    ) -> CheckoutSession:
        """Create a Payment Link; its ``short_url`` is the checkout URL.

        Razorpay Payment Links have a single ``callback_url`` — the customer
        returns to ``success_url``; ``cancel_url`` has no Payment Link
        equivalent and is unused (abandoned links simply expire).
        """
        link = self._client().payment_link.create(
            {
                "amount": to_minor_units(payment.amount, payment.currency),
                "currency": payment.currency.upper(),
                "callback_url": success_url,
                "callback_method": "get",
                "notes": {"karni_payment_id": str(payment.pk)},
            }
        )
        return CheckoutSession(id=link["id"], url=link["short_url"])

    def create_refund(self, refund: Refund) -> str:
        """Refund (part of) the captured payment; returns the refund id."""
        created = self._client().payment.refund(
            refund.payment.provider_payment_id,
            {
                "amount": to_minor_units(refund.amount, refund.payment.currency),
                "notes": {"karni_refund_id": str(refund.pk)},
            },
        )
        return str(created["id"])

    def parse_webhook(self, body: bytes, headers: Mapping[str, str]) -> ParsedEvent:
        """Verify signature + event-id header, then map the event."""
        secret = str(conf.get("RAZORPAY_WEBHOOK_SECRET"))
        if not secret:
            raise KarniImproperlyConfigured(
                "RAZORPAY_WEBHOOK_SECRET is not set, so Razorpay webhooks cannot be verified "
                "and are refused. Copy the webhook secret from the Razorpay dashboard.",
                code="PAY005",
            )
        event_id = headers.get(EVENT_ID_HEADER, "")
        if not event_id:
            raise WebhookVerificationError(f"missing {EVENT_ID_HEADER} header")
        signature = headers.get(SIGNATURE_HEADER, "")
        sdk = _razorpay_sdk()
        try:
            sdk.Utility().verify_webhook_signature(body.decode("utf-8"), signature, secret)
        except Exception as exc:
            raise WebhookVerificationError(str(exc)) from exc
        payload: dict[str, Any] = json.loads(body)
        return self.map_event(event_id, str(payload.get("event", "")), payload)

    def map_event(self, event_id: str, event_type: str, payload: dict[str, Any]) -> ParsedEvent:
        """Map a Razorpay event onto the closed status vocabulary (pure)."""

        def entity(kind: str) -> dict[str, Any]:
            return ((payload.get("payload") or {}).get(kind) or {}).get("entity") or {}

        provider_payment_id: str | None = None
        checkout_session_id: str | None = None
        if event_type.startswith("payment_link."):
            checkout_session_id = entity("payment_link").get("id")
            provider_payment_id = entity("payment").get("id")
        elif event_type.startswith("refund."):
            provider_payment_id = entity("refund").get("payment_id")
        elif event_type.startswith("payment."):
            provider_payment_id = entity("payment").get("id")
        return ParsedEvent(
            event_id=event_id,
            event_type=event_type,
            provider_payment_id=provider_payment_id,
            checkout_session_id=checkout_session_id,
            status=self.EVENT_STATUS.get(event_type),
            raw=payload,
        )
