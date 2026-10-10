"""Stripe provider: Checkout Sessions, refunds, signed webhooks.

The ``stripe`` SDK is imported lazily so the module imports without the
extra installed; the first real use raises an install hint
(``pip install "karni-payments[stripe]"``). Credentials
(``STRIPE_SECRET_KEY`` / ``STRIPE_WEBHOOK_SECRET``) are read per call and
validated lazily.

Native event → :class:`ParsedEventStatus` mapping (amendment G4):

========================================  =================
``checkout.session.completed``            ``succeeded``
``checkout.session.expired``              ``expired``
``payment_intent.succeeded``              ``succeeded``
``payment_intent.payment_failed``         ``failed``
``charge.refunded``                       ``refund_succeeded``
anything else                             ``None`` (no-op)
========================================  =================

Override / escape hatch: subclass and extend ``EVENT_STATUS`` (or override
:meth:`map_event`) for more event types, then point
``KARNI_PAYMENTS_PROVIDER`` at your subclass's dotted path.
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

__all__ = ["StripeProvider"]


def _stripe_sdk() -> Any:
    """Import the ``stripe`` SDK lazily, with an install hint on failure."""
    try:
        import stripe
    except ImportError as exc:
        raise KarniImproperlyConfigured(
            "The Stripe provider needs the stripe SDK — install the extra: "
            'pip install "karni-payments[stripe]".',
            code="PAY003",
        ) from exc
    return stripe


class StripeProvider(PaymentProvider):
    """Stripe gateway adapter (hosted Checkout Sessions)."""

    name: ClassVar[str] = "stripe"

    EVENT_STATUS: ClassVar[dict[str, ParsedEventStatus]] = {
        "checkout.session.completed": ParsedEventStatus.SUCCEEDED,
        "checkout.session.expired": ParsedEventStatus.EXPIRED,
        "payment_intent.succeeded": ParsedEventStatus.SUCCEEDED,
        "payment_intent.payment_failed": ParsedEventStatus.FAILED,
        "charge.refunded": ParsedEventStatus.REFUND_SUCCEEDED,
    }

    def _secret_key(self) -> str:
        key = str(conf.get("STRIPE_SECRET_KEY"))
        if not key:
            raise KarniImproperlyConfigured(
                "STRIPE_SECRET_KEY is not set — the Stripe provider cannot make API calls. "
                "Set it in the environment (.env in development), or use "
                "KARNI_PAYMENTS_PROVIDER = 'test' locally.",
                code="PAY004",
            )
        return key

    def create_checkout(
        self, payment: Payment, success_url: str, cancel_url: str
    ) -> CheckoutSession:
        """Create a Stripe Checkout Session in ``payment`` mode."""
        stripe = _stripe_sdk()
        session = stripe.checkout.Session.create(
            api_key=self._secret_key(),
            mode="payment",
            line_items=[
                {
                    "price_data": {
                        "currency": payment.currency.lower(),
                        "unit_amount": to_minor_units(payment.amount, payment.currency),
                        "product_data": {"name": f"Payment {payment.pk}"},
                    },
                    "quantity": 1,
                }
            ],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"karni_payment_id": str(payment.pk)},
        )
        return CheckoutSession(id=session["id"], url=session["url"])

    def create_refund(self, refund: Refund) -> str:
        """Refund (part of) the payment's PaymentIntent; returns the refund id."""
        stripe = _stripe_sdk()
        created = stripe.Refund.create(
            api_key=self._secret_key(),
            payment_intent=refund.payment.provider_payment_id,
            amount=to_minor_units(refund.amount, refund.payment.currency),
            metadata={"karni_refund_id": str(refund.pk)},
        )
        return str(created["id"])

    def parse_webhook(self, body: bytes, headers: Mapping[str, str]) -> ParsedEvent:
        """Verify the ``Stripe-Signature`` header, then map the event."""
        stripe = _stripe_sdk()
        secret = str(conf.get("STRIPE_WEBHOOK_SECRET"))
        if not secret:
            raise KarniImproperlyConfigured(
                "STRIPE_WEBHOOK_SECRET is not set — Stripe webhooks cannot be verified, so "
                "they are refused. Copy the endpoint's signing secret (whsec_...) from the "
                "Stripe dashboard.",
                code="PAY005",
            )
        signature = headers.get("Stripe-Signature", "")
        try:
            stripe.Webhook.construct_event(body, signature, secret)
        except Exception as exc:
            # Any construct_event failure (bad signature, malformed payload)
            # means the delivery is untrusted — one 400, nothing persisted.
            raise WebhookVerificationError(str(exc)) from exc
        payload: dict[str, Any] = json.loads(body)
        return self.map_event(str(payload.get("id", "")), str(payload.get("type", "")), payload)

    def map_event(self, event_id: str, event_type: str, payload: dict[str, Any]) -> ParsedEvent:
        """Map a Stripe event onto the closed status vocabulary (pure)."""
        data: dict[str, Any] = (payload.get("data") or {}).get("object") or {}
        provider_payment_id: str | None = None
        checkout_session_id: str | None = None
        if event_type.startswith("checkout.session."):
            checkout_session_id = data.get("id")
            provider_payment_id = data.get("payment_intent")
        elif event_type.startswith("payment_intent."):
            provider_payment_id = data.get("id")
        elif event_type.startswith("charge."):
            provider_payment_id = data.get("payment_intent")
        return ParsedEvent(
            event_id=event_id,
            event_type=event_type,
            provider_payment_id=provider_payment_id,
            checkout_session_id=checkout_session_id,
            status=self.EVENT_STATUS.get(event_type),
            raw=payload,
        )
