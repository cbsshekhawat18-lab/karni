"""In-memory test provider — no network, deterministic ids, real signatures.

Used by karni-payments' own suite **and** meant for projects' tests: set
``KARNI_PAYMENTS_PROVIDER = "test"`` in your test settings and the full
checkout → webhook → state-machine pipeline runs without a gateway.

Webhook format: the body is a JSON object like::

    {"id": "evt_1", "type": "payment.succeeded", "status": "succeeded",
     "payment_id": "...", "checkout_session_id": "..."}

where ``status`` is a :class:`ParsedEventStatus` value (or absent for a
no-op event), signed with ``X-Test-Signature: sha256(body + secret)``.
:meth:`TestProvider.build_webhook` assembles body + headers for you.

Override / escape hatch: subclass to change ``secret`` or the id scheme;
:meth:`TestProvider.reset` restores the deterministic counters between
tests.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from itertools import count
from typing import TYPE_CHECKING, Any, ClassVar

from karni_payments.providers.base import (
    CheckoutSession,
    ParsedEvent,
    ParsedEventStatus,
    PaymentProvider,
    WebhookVerificationError,
)

if TYPE_CHECKING:
    from karni_payments.models import Payment, Refund

__all__ = ["TestProvider"]


class TestProvider(PaymentProvider):
    """Deterministic in-memory provider for test suites."""

    name: ClassVar[str] = "test"
    secret: ClassVar[str] = "karni-test-secret"
    signature_header: ClassVar[str] = "X-Test-Signature"

    _sequence: ClassVar[count[int]] = count(1)
    sessions: ClassVar[dict[str, str]] = {}
    """Created checkout session id → payment pk."""
    refunds: ClassVar[dict[str, str]] = {}
    """Created provider refund id → refund pk."""

    @classmethod
    def reset(cls) -> None:
        """Restore deterministic state (call between tests)."""
        cls._sequence = count(1)
        cls.sessions.clear()
        cls.refunds.clear()

    @classmethod
    def sign(cls, body: bytes) -> str:
        """The signature for ``body``: hex sha256 of body + secret."""
        return hashlib.sha256(body + cls.secret.encode()).hexdigest()

    @classmethod
    def build_webhook(cls, event: Mapping[str, Any]) -> tuple[bytes, dict[str, str]]:
        """Return ``(body, headers)`` for a signed test webhook delivery."""
        body = json.dumps(dict(event)).encode()
        return body, {cls.signature_header: cls.sign(body)}

    def create_checkout(
        self, payment: Payment, success_url: str, cancel_url: str
    ) -> CheckoutSession:
        """Issue a deterministic session id and remember the payment."""
        number = next(self._sequence)
        session = CheckoutSession(
            id=f"test_cs_{number}", url=f"https://checkout.test/pay/test_cs_{number}"
        )
        self.sessions[session.id] = str(payment.pk)
        return session

    def create_refund(self, refund: Refund) -> str:
        """Issue a deterministic refund id and remember the refund."""
        provider_refund_id = f"test_re_{next(self._sequence)}"
        self.refunds[provider_refund_id] = str(refund.pk)
        return provider_refund_id

    def parse_webhook(self, body: bytes, headers: Mapping[str, str]) -> ParsedEvent:
        """Verify the sha256 signature, then map the JSON event."""
        signature = headers.get(self.signature_header, "")
        if not hmac.compare_digest(signature, self.sign(body)):
            raise WebhookVerificationError("test webhook signature mismatch")
        payload: dict[str, Any] = json.loads(body)
        return self.map_event(str(payload.get("id", "")), str(payload.get("type", "")), payload)

    def map_event(self, event_id: str, event_type: str, payload: dict[str, Any]) -> ParsedEvent:
        """Map a test event: ``status`` is carried literally in the payload."""
        raw_status = payload.get("status")
        return ParsedEvent(
            event_id=event_id,
            event_type=event_type,
            provider_payment_id=payload.get("payment_id"),
            checkout_session_id=payload.get("checkout_session_id"),
            status=ParsedEventStatus(raw_status) if raw_status else None,
            raw=payload,
        )
