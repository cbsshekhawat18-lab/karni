"""karni-payments' error codes (prefix ``PAY``), registered with Karni's registry.

Exposed through the ``karni.errorcodes`` entry point, so ``karni explain PAY004``
and ``docs/errors.md`` include them. Codes are permanent: never renumber or
reuse one; append new codes at the end.
"""

from __future__ import annotations

from typing import Final

from karni.errorcodes import ErrorCode

__all__ = ["CODES"]

_SOURCE = "karni_payments"

CODES: Final[tuple[ErrorCode, ...]] = (
    ErrorCode(
        code="PAY001",
        title="KARNI_PAYMENTS_PROVIDER cannot be loaded",
        kind="exception",
        source=f"{_SOURCE}.providers.base.get_provider",
        why="Every checkout, refund and webhook goes through the configured provider class.",
        fix="Set KARNI_PAYMENTS_PROVIDER to a shortcut ('stripe', 'razorpay', 'test') or the "
        "dotted path of a karni_payments.providers.base.PaymentProvider subclass.",
    ),
    ErrorCode(
        code="PAY002",
        title="No payment provider has that name",
        kind="exception",
        source=f"{_SOURCE}.providers.base.get_provider_by_name",
        why="Webhooks and stored payments name the provider that handled them.",
        fix="Use the configured provider's name or a shortcut: stripe, razorpay, test.",
    ),
    ErrorCode(
        code="PAY003",
        title="The payment provider's SDK is not installed",
        kind="exception",
        source=f"{_SOURCE}.providers (stripe, razorpay)",
        why="Provider SDKs are optional extras so a project installs only the one it uses.",
        fix="Install the extra: pip install 'karni-payments[stripe]' or "
        "'karni-payments[razorpay]'.",
    ),
    ErrorCode(
        code="PAY004",
        title="The payment provider's API credentials are not set",
        kind="exception",
        source=f"{_SOURCE}.providers (stripe, razorpay)",
        why="The provider cannot create checkouts or refunds without its API keys.",
        fix="Set STRIPE_SECRET_KEY (Stripe) or RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET "
        "(Razorpay) in the environment (.env in development). Use the 'test' provider "
        "for local work without keys.",
    ),
    ErrorCode(
        code="PAY005",
        title="The webhook signing secret is not set",
        kind="exception",
        source=f"{_SOURCE}.providers (stripe, razorpay)",
        why="Unverified webhooks could mark any payment as paid, so Karni refuses them.",
        fix="Set STRIPE_WEBHOOK_SECRET or RAZORPAY_WEBHOOK_SECRET to the secret shown in "
        "the provider's dashboard for this webhook endpoint.",
    ),
    ErrorCode(
        code="PAY006",
        title="A webhook failed signature verification",
        kind="exception",
        source=f"{_SOURCE}.webhooks (answered with HTTP 400, never stored)",
        why="The payload was not signed with this endpoint's secret: a forged request, or a "
        "secret that does not match the provider's dashboard.",
        fix="If the webhook is genuine, copy the endpoint's signing secret from the "
        "provider's dashboard into the *_WEBHOOK_SECRET setting. Otherwise nothing to do: "
        "the request was rejected.",
    ),
    ErrorCode(
        code="PAY007",
        title="The currency or amount cannot be charged exactly",
        kind="exception",
        source=f"{_SOURCE}.providers.base.to_minor_units",
        why="Providers charge integer minor units (cents); Karni never rounds money "
        "silently, and 3-decimal currencies are not supported yet.",
        fix="Round the amount to the currency's minor unit before charging (e.g. "
        "Decimal('10.50')), and charge in a 0- or 2-decimal currency.",
    ),
    ErrorCode(
        code="PAY008",
        title="A checkout redirect URL points at an origin that is not allowed",
        kind="api",
        source=f"{_SOURCE}.services.create_checkout",
        why="An open redirect after payment would let attackers send customers anywhere.",
        fix="Redirect to your frontend (KARNI_FRONTEND_URL), or add the origin to "
        "KARNI_PAYMENTS_ALLOWED_REDIRECTS.",
    ),
    ErrorCode(
        code="PAY009",
        title="A webhook event matches no local payment",
        kind="exception",
        source=f"{_SOURCE}.services (webhook processing task)",
        why="Providers can deliver a webhook before the checkout that created the payment "
        "is committed; the task retries instead of dropping the event.",
        fix="Usually nothing: the retry succeeds. If it keeps failing, the payment was "
        "created outside Karni (or in another environment sharing the webhook): check "
        "the provider ids in the message.",
    ),
)
