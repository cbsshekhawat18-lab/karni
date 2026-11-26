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

The checkout page: while
``KARNI_PAYMENTS_TEST_CHECKOUT_PAGE`` is on (by default, while ``DEBUG``
is), a checkout started in a request gets the address of
``payments/test-checkout/<session>/`` on that request's host
(:mod:`karni_payments.test_checkout`), where a person pays or declines the
payment in a browser. Without a request, or with the page off, the address
is the imaginary ``https://checkout.test/pay/<session>``.

Override / escape hatch: subclass to change ``secret``, the id scheme or
:meth:`TestProvider.checkout_url`; :meth:`TestProvider.reset` restores the
deterministic counters between tests.
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

__all__ = ["IMAGINARY", "PAGE_KEY", "TestProvider"]

#: The checkout address when the page is off: no page answers there.
IMAGINARY = "https://checkout.test/pay/"
#: The key of ``Payment.metadata`` that holds where the page sends the person back.
PAGE_KEY = "test_checkout"


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
        """Issue a deterministic session id and remember the payment.

        The ids count up from 1 in each process. A development server that
        restarts keeps the rows of the run before, so an id a stored payment
        already has is skipped: the checkout page finds each payment by it.
        """
        from karni_payments.models import Payment

        session_id = f"test_cs_{next(self._sequence)}"
        taken = Payment.objects.filter(provider=self.name)
        while taken.filter(checkout_session_id=session_id).exists():
            session_id = f"test_cs_{next(self._sequence)}"
        url = self.checkout_url(session_id)
        if not url.startswith(IMAGINARY):
            # The page sends the person back to these once they pay or decline.
            payment.metadata = {
                **payment.metadata,
                PAGE_KEY: {"success_url": success_url, "cancel_url": cancel_url},
            }
            payment.save(update_fields=["metadata", "updated_at"])
        session = CheckoutSession(id=session_id, url=url)
        self.sessions[session.id] = str(payment.pk)
        return session

    def checkout_url(self, session_id: str) -> str:
        """Where the person pays: the checkout page, or the imaginary address."""
        from karni_payments.test_checkout import page_url

        return page_url(session_id) or f"{IMAGINARY}{session_id}"

    def create_refund(self, refund: Refund) -> str:
        """Issue a deterministic refund id and remember the refund."""
        provider_refund_id = f"test_re_{next(self._sequence)}"
        self.refunds[provider_refund_id] = str(refund.pk)
        from karni_payments import test_checkout

        if test_checkout.enabled():
            # A local try (DEBUG): the refund goes through once it is saved, as the
            # provider's webhook would say. Tests confirm their refunds themselves.
            from django.db import transaction

            payment_pk = refund.payment_id
            transaction.on_commit(lambda: _confirm(payment_pk))
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
        # A status outside the vocabulary is an event this provider does not
        # map: status=None, which the webhook records as processed with a note
        # (the contract in ParsedEventStatus), never an error the sender retries.
        try:
            status = ParsedEventStatus(str(payload["status"])) if payload.get("status") else None
        except ValueError:
            status = None
        return ParsedEvent(
            event_id=event_id,
            event_type=event_type,
            provider_payment_id=payload.get("payment_id"),
            checkout_session_id=payload.get("checkout_session_id"),
            status=status,
            raw=payload,
        )


def _confirm(payment_pk: Any) -> None:
    from karni_payments import test_checkout
    from karni_payments.models import Payment

    payment = Payment.objects.filter(pk=payment_pk).first()
    if payment is not None:
        test_checkout.confirm_refund(payment)
