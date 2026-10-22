"""Payments business logic — all state changes go through this module.

Views, viewset actions and Celery tasks stay thin; project code calls these
functions instead of provider SDKs (never call a gateway SDK directly).

Error contract:

* input problems (bad amount, disallowed redirect, over-refund) raise DRF's
  :class:`rest_framework.exceptions.ValidationError`, which the API renders
  as HTTP 400 with no per-view handling;
* a webhook event that matches no local payment raises
  :class:`UnmatchedWebhookEventError` — the Celery task re-raises it so
  retry/backoff finds the row later; the event is **never** marked processed;
* provider failures propagate after the local row is marked ``failed``.

Override / escape hatches:

* ``KARNI_PAYMENTS_CHECKOUT_VALIDATOR`` — dotted path called *before* a
  Payment exists; replace :func:`default_checkout_validator` to enforce
  server-side pricing (never trust client amounts).
* ``KARNI_PAYMENTS_EVENT_HANDLER`` — dotted path the webhook task calls
  (default :func:`apply_event`); point it at your own function to replace or
  wrap the state machine.
* ``KARNI_PAYMENTS_ALLOWED_REDIRECTS`` — extra origins allowed for checkout
  redirect URLs on top of ``KARNI_FRONTEND_URL``.
* every function is a plain module-level function — call your own instead
  from an overridden viewset action for anything these do not cover.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils.module_loading import import_string
from karni.debug import trace_event
from karni.errorcodes import KarniError
from karni.exceptions import api_error
from rest_framework.exceptions import ValidationError

from karni_payments import conf
from karni_payments.models import Payment, Refund, WebhookEvent
from karni_payments.providers.base import (
    CheckoutSession,
    ParsedEvent,
    ParsedEventStatus,
    get_provider,
    get_provider_by_name,
)

if TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser

__all__ = [
    "UnmatchedWebhookEventError",
    "apply_event",
    "create_checkout",
    "create_refund",
    "default_checkout_validator",
    "refunded_amount",
]

logger = logging.getLogger(__name__)

#: Refund statuses that hold (or may still claim) money — the remainder a
#: new refund is validated against counts both (amendment G5).
REFUND_COUNTED_STATUSES: tuple[str, ...] = (Refund.Status.PENDING, Refund.Status.SUCCEEDED)


class UnmatchedWebhookEventError(KarniError):
    """A webhook event references a payment this database does not hold (yet).

    Raised — never swallowed — so the Celery task's retry/backoff can find
    the payment once the checkout transaction has landed.
    """

    code = "PAY009"


def default_checkout_validator(
    *,
    user: AbstractBaseUser | None,
    amount: Decimal,
    currency: str,
    metadata: dict[str, Any],
) -> None:
    """The default ``KARNI_PAYMENTS_CHECKOUT_VALIDATOR``: a pass-through.

    Replace it (dotted path in settings) to enforce server-side pricing —
    e.g. look the price up from ``metadata["sku"]`` and raise
    ``ValidationError`` when ``amount`` disagrees. Never trust client
    amounts in production.
    """


def _allowed_redirect_origins() -> set[str]:
    """Origins checkout redirect URLs may target.

    ``KARNI_FRONTEND_URL``'s origin plus the origins of every entry in
    ``KARNI_PAYMENTS_ALLOWED_REDIRECTS``.
    """
    candidates = [str(getattr(settings, "KARNI_FRONTEND_URL", "") or "")]
    candidates += [str(entry) for entry in conf.get("KARNI_PAYMENTS_ALLOWED_REDIRECTS")]
    origins: set[str] = set()
    for candidate in candidates:
        parts = urlsplit(candidate)
        if parts.scheme and parts.netloc:
            origins.add(f"{parts.scheme}://{parts.netloc}")
    return origins


def _validate_redirect_url(url: str, field: str) -> None:
    """Reject a redirect URL whose origin is not explicitly allowed."""
    parts = urlsplit(str(url))
    origin = f"{parts.scheme}://{parts.netloc}"
    if not parts.scheme or not parts.netloc or origin not in _allowed_redirect_origins():
        raise api_error(
            "PAY008",
            f"Origin {origin!r} is not an allowed checkout redirect target. Redirect to "
            "KARNI_FRONTEND_URL, or add the origin to KARNI_PAYMENTS_ALLOWED_REDIRECTS.",
            field=field,
        )


def create_checkout(
    user: AbstractBaseUser | None,
    *,
    amount: Decimal,
    success_url: str,
    cancel_url: str,
    currency: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[Payment, CheckoutSession]:
    """Create a pending :class:`Payment` plus its provider checkout session.

    Order of operations (amendment G2): the configured checkout validator
    runs first (server-side authority, before any row exists), the redirect
    URLs are origin-checked, then the Payment is created and the provider
    session opened. A provider failure marks the payment ``failed`` before
    re-raising, so abandoned rows are visible, not silently pending.

    :returns: ``(payment, session)`` — redirect the customer to
        ``session.url``.
    :raises rest_framework.exceptions.ValidationError: for bad input.
    """
    amount = Decimal(amount)
    if amount <= 0:
        raise ValidationError({"amount": ["Amount must be positive."]})
    currency = str(currency or conf.get("KARNI_PAYMENTS_CURRENCY")).lower()
    metadata = dict(metadata or {})

    validator = import_string(conf.get("KARNI_PAYMENTS_CHECKOUT_VALIDATOR"))
    validator(user=user, amount=amount, currency=currency, metadata=metadata)
    _validate_redirect_url(success_url, "success_url")
    _validate_redirect_url(cancel_url, "cancel_url")

    provider = get_provider()
    payment = Payment.objects.create(
        user=user,
        amount=amount,
        currency=currency,
        metadata=metadata,
        provider=provider.name,
        status=Payment.Status.PENDING,
    )
    try:
        session = provider.create_checkout(payment, success_url, cancel_url)
    except Exception:
        payment.status = Payment.Status.FAILED
        payment.save(update_fields=["status", "updated_at"])
        raise
    payment.checkout_session_id = session.id
    payment.save(update_fields=["checkout_session_id", "updated_at"])
    # Development trace (DEBUG only): the webhook that settles this payment
    # names the same ref, so `karni trace` links the two requests.
    trace_event(
        "payment.checkout",
        provider=provider.name,
        amount=str(amount),
        currency=currency,
        refs=[_ref(payment)],
    )
    return payment, session


def _ref(row: Payment | Refund | WebhookEvent) -> str:
    """``karni_payments.Payment:<pk>`` — how trace events name a row."""
    return f"{row._meta.label}:{row.pk}"


def refunded_amount(payment: Payment) -> Decimal:
    """Sum of this payment's refunds that hold or may still claim money."""
    total = payment.refunds.filter(status__in=REFUND_COUNTED_STATUSES).aggregate(
        total=Sum("amount")
    )["total"]
    return total if total is not None else Decimal("0")


def create_refund(payment: Payment, amount: Decimal | None = None, *, reason: str = "") -> Refund:
    """Create a refund for ``payment`` (``amount=None`` → the full remainder).

    Accounting is non-negotiable (amendment G5): inside one
    ``transaction.atomic`` block the Payment row is locked with
    ``select_for_update`` and the requested amount validated against
    ``payment.amount`` minus the sum of refunds in ``pending``/``succeeded``
    — so concurrent refunds can never over-refund (the lock is effective on
    PostgreSQL; sqlite serialises writes anyway).

    The provider call happens *after* that transaction commits (no network
    I/O under a row lock); a provider failure marks the refund ``failed``
    and re-raises. Status advances to ``succeeded`` via the provider's
    refund webhook, not here.

    :raises rest_framework.exceptions.ValidationError: when nothing is left
        to refund or the amount exceeds the unrefunded remainder.
    """
    with transaction.atomic():
        locked = Payment.objects.select_for_update().get(pk=payment.pk)
        remaining = locked.amount - refunded_amount(locked)
        if remaining <= 0:
            raise ValidationError({"amount": ["Nothing left to refund on this payment."]})
        amount = Decimal(amount) if amount is not None else remaining
        if amount <= 0:
            raise ValidationError({"amount": ["Refund amount must be positive."]})
        if amount > remaining:
            raise ValidationError(
                {"amount": [f"Refund exceeds the unrefunded remainder ({remaining})."]}
            )
        refund = Refund.objects.create(
            payment=locked,
            amount=amount,
            reason=reason,
            status=Refund.Status.PENDING,
        )
    provider = get_provider_by_name(locked.provider)
    try:
        provider_refund_id = provider.create_refund(refund)
    except Exception:
        refund.status = Refund.Status.FAILED
        refund.save(update_fields=["status", "updated_at"])
        raise
    refund.provider_refund_id = provider_refund_id
    refund.save(update_fields=["provider_refund_id", "updated_at"])
    return refund


# ---------------------------------------------------------------------------
# The webhook state machine (default KARNI_PAYMENTS_EVENT_HANDLER)
# ---------------------------------------------------------------------------

#: Monotonic payment ladder (amendment G3): which statuses each status may
#: still advance to. Terminal statuses never regress; anything not listed is
#: a no-op recorded as a note.
PAYMENT_ADVANCES: dict[str, frozenset[str]] = {
    Payment.Status.PENDING: frozenset(
        {
            Payment.Status.PROCESSING,
            Payment.Status.SUCCEEDED,
            Payment.Status.FAILED,
            Payment.Status.CANCELED,
        }
    ),
    Payment.Status.PROCESSING: frozenset(
        {Payment.Status.SUCCEEDED, Payment.Status.FAILED, Payment.Status.CANCELED}
    ),
    Payment.Status.SUCCEEDED: frozenset(
        {Payment.Status.PARTIALLY_REFUNDED, Payment.Status.REFUNDED}
    ),
    Payment.Status.PARTIALLY_REFUNDED: frozenset({Payment.Status.REFUNDED}),
    Payment.Status.REFUNDED: frozenset(),
    Payment.Status.FAILED: frozenset(),
    Payment.Status.CANCELED: frozenset(),
}

#: Non-refund event statuses → target payment status (``expired`` sessions
#: map to ``canceled`` — amendment G4).
_EVENT_TARGET: dict[ParsedEventStatus, str] = {
    ParsedEventStatus.PROCESSING: Payment.Status.PROCESSING,
    ParsedEventStatus.SUCCEEDED: Payment.Status.SUCCEEDED,
    ParsedEventStatus.FAILED: Payment.Status.FAILED,
    ParsedEventStatus.CANCELED: Payment.Status.CANCELED,
    ParsedEventStatus.EXPIRED: Payment.Status.CANCELED,
}


def _note(event: WebhookEvent, text: str) -> None:
    """Record a processing note on the event (it still counts as processed)."""
    event.error = text
    event.save(update_fields=["error", "updated_at"])


def _match_payment(event: WebhookEvent, parsed: ParsedEvent) -> Payment:
    """Find the local Payment a parsed event refers to, or raise.

    Matches on ``(provider, provider_payment_id)`` first, then on the
    checkout session id — webhooks can arrive before the provider payment id
    has been stored locally.
    """
    payment = None
    if parsed.provider_payment_id:
        payment = Payment.objects.filter(
            provider=event.provider, provider_payment_id=parsed.provider_payment_id
        ).first()
    if payment is None and parsed.checkout_session_id:
        payment = Payment.objects.filter(
            provider=event.provider, checkout_session_id=parsed.checkout_session_id
        ).first()
    if payment is not None:
        trace_event(
            "webhook.matched",
            provider=event.provider,
            event_id=event.event_id,
            event_type=event.event_type,
            refs=[_ref(payment), _ref(event)],
        )
        return payment
    raise UnmatchedWebhookEventError(
        f"Webhook event {event.provider}:{event.event_id} ({event.event_type}) "
        "matches no local Payment. It will be retried."
    )


def _apply_refund_event(event: WebhookEvent, payment: Payment, status: ParsedEventStatus) -> None:
    """Flip pending refunds per the event and recompute the payment status.

    v0.1 simplification (documented): provider refund events carry no local
    refund identity in :class:`ParsedEvent`, so **all** pending refunds of
    the payment flip together. Refunds issued directly in a provider
    dashboard (no local Refund row) only leave a note.
    """
    pending = list(payment.refunds.filter(status=Refund.Status.PENDING))
    if status is ParsedEventStatus.REFUND_FAILED:
        for refund in pending:
            refund.status = Refund.Status.FAILED
            refund.save(update_fields=["status", "updated_at"])
        if not pending:
            _note(event, "no-op: refund_failed with no pending refunds")
        return
    for refund in pending:
        refund.status = Refund.Status.SUCCEEDED
        refund.save(update_fields=["status", "updated_at"])
    succeeded_total = payment.refunds.filter(status=Refund.Status.SUCCEEDED).aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0")
    if succeeded_total >= payment.amount:
        target = Payment.Status.REFUNDED
    elif succeeded_total > 0:
        target = Payment.Status.PARTIALLY_REFUNDED
    else:
        _note(event, "no-op: refund event with no local refunds recorded")
        return
    if target == payment.status:
        return
    if target not in PAYMENT_ADVANCES[payment.status]:
        _note(event, f"no-op: {payment.status} -> {target} would regress")
        return
    payment.status = target
    payment.save(update_fields=["status", "updated_at"])


def apply_event(event: WebhookEvent) -> None:
    """The default webhook state machine (``KARNI_PAYMENTS_EVENT_HANDLER``).

    Maps the stored event back through the provider's
    :meth:`~karni_payments.providers.base.PaymentProvider.map_event` table
    and advances the matched Payment / its Refunds **monotonically**
    (amendment G3): terminal statuses never regress, non-advancing and
    unknown events are recorded as a "no-op:" note and count as processed,
    and an event matching no payment raises
    :class:`UnmatchedWebhookEventError` for the task to retry.

    Idempotent per event: re-applying a processed event finds the statuses
    already advanced and records a no-op note.

    Override / escape hatch: point ``KARNI_PAYMENTS_EVENT_HANDLER`` at your
    own ``(event) -> None`` callable to replace this, or wrap it (import and
    call ``apply_event`` from yours) to add project side effects such as
    fulfilment.
    """
    provider = get_provider_by_name(event.provider)
    parsed = provider.map_event(event.event_id, event.event_type, event.payload)
    if parsed.status is None:
        _note(event, f"no-op: unhandled event type {event.event_type!r}")
        return
    payment = _match_payment(event, parsed)
    if parsed.provider_payment_id and not payment.provider_payment_id:
        payment.provider_payment_id = parsed.provider_payment_id
        payment.save(update_fields=["provider_payment_id", "updated_at"])
    if parsed.status in (ParsedEventStatus.REFUND_SUCCEEDED, ParsedEventStatus.REFUND_FAILED):
        _apply_refund_event(event, payment, parsed.status)
        return
    target = _EVENT_TARGET[parsed.status]
    if target == payment.status:
        _note(event, f"no-op: payment already {payment.status}")
        return
    if target not in PAYMENT_ADVANCES[payment.status]:
        _note(event, f"no-op: {payment.status} -> {target} would regress")
        return
    payment.status = target
    payment.save(update_fields=["status", "updated_at"])
