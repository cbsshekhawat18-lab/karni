"""The payment provider contract and shared provider utilities.

A provider turns Karni's provider-agnostic vocabulary (checkout, refund,
webhook event) into one gateway's API calls. Implementations must:

* create hosted checkout sessions (:meth:`PaymentProvider.create_checkout`),
* create refunds (:meth:`PaymentProvider.create_refund`),
* verify **and** parse webhooks (:meth:`PaymentProvider.parse_webhook` —
  signature verification is mandatory, failure raises
  :class:`WebhookVerificationError`),
* map native event types onto the closed :class:`ParsedEventStatus` enum
  (:meth:`PaymentProvider.map_event` — pure, reused by the webhook task).

Override / escape hatch: set ``KARNI_PAYMENTS_PROVIDER`` to ``"stripe"``,
``"razorpay"``, ``"test"`` or **any dotted path** to your own
:class:`PaymentProvider` subclass; the instance is cached and the cache is
reset on ``setting_changed`` (so ``override_settings`` works in tests).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar

from django.test.signals import setting_changed
from django.utils.module_loading import import_string
from karni.errorcodes import KarniError
from karni.exceptions import KarniImproperlyConfigured, KarniLookupError, KarniValueError

from karni_payments import conf

if TYPE_CHECKING:
    from karni_payments.models import Payment, Refund

__all__ = [
    "PROVIDER_SHORTCUTS",
    "THREE_DECIMAL_CURRENCIES",
    "ZERO_DECIMAL_CURRENCIES",
    "CheckoutSession",
    "ParsedEvent",
    "ParsedEventStatus",
    "PaymentProvider",
    "UnsupportedCurrencyError",
    "WebhookVerificationError",
    "from_minor_units",
    "get_provider",
    "get_provider_by_name",
    "to_minor_units",
]


class WebhookVerificationError(KarniError):
    """A webhook's signature (or required identity header) failed verification.

    The webhook view maps this to an **unpersisted** HTTP 400 plus one
    structured warning log — forged payloads never reach the database.
    """

    code = "PAY006"


class UnsupportedCurrencyError(KarniValueError):
    """The currency cannot be converted to integer minor units.

    Raised for 3-decimal currencies (unsupported in karni-payments v0.1) and
    for amounts with sub-minor-unit fractions.
    """

    code = "PAY007"


# Currencies whose minor unit equals the major unit (amount 500 JPY is sent
# as 500, not 50000). The Stripe/Razorpay zero-decimal set.
ZERO_DECIMAL_CURRENCIES: frozenset[str] = frozenset(
    {
        "bif",
        "clp",
        "djf",
        "gnf",
        "jpy",
        "kmf",
        "krw",
        "mga",
        "pyg",
        "rwf",
        "ugx",
        "vnd",
        "vuv",
        "xaf",
        "xof",
        "xpf",
    }
)

# Three-decimal currencies are deliberately unsupported in v0.1: providers
# impose extra rounding rules on them (e.g. Stripe requires the last digit
# to be 0) that a generic converter cannot honour safely.
THREE_DECIMAL_CURRENCIES: frozenset[str] = frozenset({"bhd", "jod", "kwd", "omr", "tnd"})


def _currency_exponent(currency: str) -> int:
    code = currency.lower()
    if code in THREE_DECIMAL_CURRENCIES:
        raise UnsupportedCurrencyError(
            f"3-decimal currency {currency!r} is not supported by karni-payments v0.1: "
            "providers need integer minor units and these need special rounding. Charge "
            "in a 0- or 2-decimal currency."
        )
    return 0 if code in ZERO_DECIMAL_CURRENCIES else 2


def to_minor_units(amount: Decimal, currency: str) -> int:
    """Convert a decimal major-unit amount to the provider's integer minor units.

    ``Decimal("10.50"), "usd"`` → ``1050``; ``Decimal("500"), "jpy"`` →
    ``500``. Raises :class:`UnsupportedCurrencyError` for 3-decimal
    currencies and for amounts that do not land on a whole minor unit
    (never silently rounds — it's money).
    """
    minor = Decimal(amount).scaleb(_currency_exponent(currency))
    if minor != minor.to_integral_value():
        raise UnsupportedCurrencyError(
            f"Amount {amount} has sub-minor-unit precision for currency {currency!r}, and "
            "Karni never rounds money silently. Round it to the currency's minor unit "
            "(e.g. Decimal('10.50')) before charging."
        )
    return int(minor)


def from_minor_units(minor: int, currency: str) -> Decimal:
    """Convert a provider's integer minor units back to a decimal amount.

    The inverse of :func:`to_minor_units`: ``1050, "usd"`` →
    ``Decimal("10.50")``; ``500, "jpy"`` → ``Decimal("500")``.
    """
    exponent = _currency_exponent(currency)
    return Decimal(minor).scaleb(-exponent).quantize(Decimal(1).scaleb(-exponent))


class ParsedEventStatus(StrEnum):
    """The closed vocabulary provider events are mapped onto (amendment G4).

    ``EXPIRED`` (an abandoned checkout session) advances the payment to
    ``canceled``; the refund statuses drive refund accounting instead of the
    payment ladder. Events outside a provider's mapping table parse with
    ``status=None`` and are marked processed with a note.
    """

    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REFUND_SUCCEEDED = "refund_succeeded"
    REFUND_FAILED = "refund_failed"


@dataclass(frozen=True)
class CheckoutSession:
    """A provider-hosted checkout the customer is redirected to."""

    id: str
    url: str


@dataclass(frozen=True)
class ParsedEvent:
    """A verified webhook delivery in provider-agnostic terms.

    ``raw`` is the JSON-decoded payload exactly as delivered (persisted on
    :class:`~karni_payments.models.WebhookEvent` so
    :meth:`PaymentProvider.map_event` can re-derive everything later).
    """

    event_id: str
    event_type: str
    provider_payment_id: str | None = None
    checkout_session_id: str | None = None
    status: ParsedEventStatus | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class PaymentProvider(ABC):
    """Abstract payment gateway adapter.

    Subclass it to integrate a gateway Karni does not ship: implement the
    four abstract methods, give the class a unique ``name``, and point
    ``KARNI_PAYMENTS_PROVIDER`` at its dotted path. Credentials must be read
    lazily (per call, via :func:`karni_payments.conf.get`) so missing keys
    fail at use, not at boot, and ``override_settings`` works in tests.
    """

    name: ClassVar[str]
    """Unique short name; stored on ``Payment.provider`` and used in the
    webhook URL (``webhook/<name>/``)."""

    @abstractmethod
    def create_checkout(
        self, payment: Payment, success_url: str, cancel_url: str
    ) -> CheckoutSession:
        """Create a hosted checkout session for ``payment``.

        Returns the provider's session id and redirect URL. May raise any
        provider error — ``services.create_checkout`` marks the payment
        failed and re-raises.
        """

    @abstractmethod
    def create_refund(self, refund: Refund) -> str:
        """Create a refund at the provider and return the provider refund id."""

    @abstractmethod
    def parse_webhook(self, body: bytes, headers: Mapping[str, str]) -> ParsedEvent:
        """Verify a webhook delivery's signature and parse it.

        MUST verify the provider signature (and any identity headers) before
        trusting the body, raising :class:`WebhookVerificationError` on any
        failure. On success, delegates the vocabulary mapping to
        :meth:`map_event`.
        """

    @abstractmethod
    def map_event(self, event_id: str, event_type: str, payload: dict[str, Any]) -> ParsedEvent:
        """Map a native event onto the :class:`ParsedEventStatus` vocabulary.

        Pure (no I/O, no signature concerns): called by :meth:`parse_webhook`
        on receipt and again by ``services.apply_event`` when the stored
        :class:`~karni_payments.models.WebhookEvent` is processed. Unknown
        event types return ``status=None``.
        """


PROVIDER_SHORTCUTS: dict[str, str] = {
    "stripe": "karni_payments.providers.stripe.StripeProvider",
    "razorpay": "karni_payments.providers.razorpay.RazorpayProvider",
    "test": "karni_payments.providers.test.TestProvider",
}
"""Shortcut names accepted by ``KARNI_PAYMENTS_PROVIDER`` and webhook URLs."""

_provider_cache: dict[str, PaymentProvider] = {}


def get_provider(name: str | None = None) -> PaymentProvider:
    """Resolve and cache a provider instance.

    With no argument, resolves the ``KARNI_PAYMENTS_PROVIDER`` setting;
    otherwise resolves ``name``. Either value may be a shortcut
    (:data:`PROVIDER_SHORTCUTS`) or a dotted path to a
    :class:`PaymentProvider` subclass — the escape hatch for custom
    gateways. Instances are cached per spec; the cache resets when any
    ``KARNI_PAYMENTS_*`` setting changes (``override_settings`` safe).

    :raises ImproperlyConfigured: when the spec cannot be imported or does
        not name a :class:`PaymentProvider` subclass.
    """
    spec = str(name or conf.get("KARNI_PAYMENTS_PROVIDER"))
    cached = _provider_cache.get(spec)
    if cached is not None:
        return cached
    path = PROVIDER_SHORTCUTS.get(spec, spec)
    try:
        provider_class = import_string(path)
    except ImportError as exc:
        raise KarniImproperlyConfigured(
            f"KARNI_PAYMENTS_PROVIDER spec {spec!r} cannot be imported: {exc}", code="PAY001"
        ) from exc
    if not (isinstance(provider_class, type) and issubclass(provider_class, PaymentProvider)):
        raise KarniImproperlyConfigured(
            f"KARNI_PAYMENTS_PROVIDER spec {spec!r} must name a "
            "karni_payments.providers.base.PaymentProvider subclass.",
            code="PAY001",
        )
    instance = provider_class()
    _provider_cache[spec] = instance
    return instance


def get_provider_by_name(name: str) -> PaymentProvider:
    """Resolve a provider by its short **name** (never a dotted path).

    Used wherever the name comes from untrusted or stored data — the webhook
    URL segment and ``Payment.provider`` — so request input can never import
    arbitrary modules. The **configured** provider wins when its ``name``
    matches (a custom subclass keeps handling its own webhooks and refunds
    even when it reuses a stock name); otherwise the shortcut names resolve.

    :raises LookupError: when no provider answers to ``name``.
    """
    configured = get_provider()
    if configured.name == name:
        return configured
    if name in PROVIDER_SHORTCUTS:
        return get_provider(name)
    raise KarniLookupError(
        f"No payment provider named {name!r} is available. Use the configured provider "
        f"({configured.name!r}) or a shortcut: {', '.join(sorted(PROVIDER_SHORTCUTS))}.",
        code="PAY002",
    )


def _reset_provider_cache(sender: object, setting: str, **kwargs: Any) -> None:
    """Drop cached provider instances when payments settings change."""
    if setting.startswith("KARNI_PAYMENTS"):
        _provider_cache.clear()


setting_changed.connect(_reset_provider_cache, dispatch_uid="karni_payments.providers.cache_reset")
