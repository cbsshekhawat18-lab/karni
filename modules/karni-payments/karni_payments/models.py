"""Payments domain models, all on :class:`karni.models.BaseModel`.

API exposure is steered by ``APIMeta`` (checkout internals excluded,
provider-owned fields read-only) and the derived admin by ``AdminMeta`` —
this module ships **no** ``admin.py``; karni.admin's autodiscovery builds the
admins from these hints.

Override / escape hatch: the usual Karni ones — redeclare ``APIMeta`` /
``AdminMeta`` effects by subclassing the viewsets, register your own admin
class (explicit registrations beat autodiscovery), or point the viewsets at a
``serializer_class`` of your own.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from karni.models import BaseModel

__all__ = ["Payment", "Refund", "WebhookEvent"]


class Payment(BaseModel):
    """One payment attempt: created pending, advanced by provider webhooks.

    ``provider_payment_id`` is the provider's payment object id (e.g. a
    Stripe PaymentIntent or a Razorpay payment id) and is unique per provider
    once set; ``checkout_session_id`` is the hosted-checkout handle (Stripe
    Checkout Session / Razorpay Payment Link) used to match webhooks that
    arrive before the payment id is known.

    Status only ever advances (see ``karni_payments.services.apply_event``):
    ``succeeded`` / ``refunded`` / ``failed`` / ``canceled`` never regress.
    """

    class Status(models.TextChoices):
        PENDING = "pending"
        PROCESSING = "processing"
        SUCCEEDED = "succeeded"
        FAILED = "failed"
        CANCELED = "canceled"
        REFUNDED = "refunded"
        PARTIALLY_REFUNDED = "partially_refunded"

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    provider = models.CharField(max_length=50)
    provider_payment_id = models.CharField(max_length=255, blank=True, default="")
    checkout_session_id = models.CharField(max_length=255, blank=True, default="")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payments",
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            # Unique per provider only once the provider assigned an id —
            # blank ids (fresh checkouts) may repeat freely.
            models.UniqueConstraint(
                fields=["provider", "provider_payment_id"],
                condition=~Q(provider_payment_id=""),
                name="karni_payments_payment_provider_id_uniq",
            ),
        ]

    class APIMeta:
        # Checkout internals stay off the API; provider-owned fields are
        # read-only (clients never write payment state).
        exclude = ["checkout_session_id"]
        read_only = ["status", "provider", "provider_payment_id"]

    class AdminMeta:
        list_display = ["amount", "currency", "status", "provider", "user", "created_at"]
        search_fields = ["provider_payment_id", "checkout_session_id"]
        read_only = ["provider", "provider_payment_id", "checkout_session_id"]

    def __str__(self) -> str:
        return f"{self.amount} {self.currency.upper()} [{self.status}]"


class Refund(BaseModel):
    """A refund against a :class:`Payment` (full or partial).

    Created ``pending`` by ``services.create_refund`` (which validates the
    unrefunded remainder under a row lock); flipped to ``succeeded`` /
    ``failed`` by provider webhooks or by a provider error during creation.
    """

    class Status(models.TextChoices):
        PENDING = "pending"
        SUCCEEDED = "succeeded"
        FAILED = "failed"

    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="refunds")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    provider_refund_id = models.CharField(max_length=255, blank=True, default="")
    reason = models.CharField(max_length=255, blank=True, default="")

    class APIMeta:
        read_only = ["payment", "amount", "status", "provider_refund_id", "reason"]

    class Karni:
        # karni.fields' CASCADE check (W965): deliberate, see the reason.
        cascade = {
            "payment": "a refund is part of its payment. Payments are soft-deleted, and a "
            "hard delete of a payment is a deliberate purge of its whole record",
        }

    class AdminMeta:
        list_display = ["payment", "amount", "status", "created_at"]
        read_only = ["provider_refund_id"]

    def __str__(self) -> str:
        return f"refund {self.amount} of {self.payment_id} [{self.status}]"


class WebhookEvent(BaseModel):
    """One received provider webhook delivery — THE dedupe record.

    ``(provider, event_id)`` is unique: redelivery of a processed event is a
    no-op, redelivery of an unprocessed one re-enqueues the task.
    ``processed_at`` is stamped by the Celery task in the same transaction as
    the state change; ``error`` carries either the last failure text or a
    "no-op:" note for events that changed nothing (unknown types,
    non-advancing transitions).
    """

    provider = models.CharField(max_length=50)
    event_id = models.CharField(max_length=255)
    event_type = models.CharField(max_length=100)
    payload = models.JSONField(default=dict)
    processed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "event_id"],
                name="karni_payments_webhook_event_dedupe",
            ),
        ]

    class AdminMeta:
        list_display = ["provider", "event_type", "event_id", "processed_at", "created_at"]
        search_fields = ["event_id", "event_type"]
        read_only = ["provider", "event_id", "event_type", "payload", "processed_at"]

    def __str__(self) -> str:
        return f"{self.provider}:{self.event_id} ({self.event_type})"
