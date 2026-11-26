"""The outbox: published events, their deliveries, and the keys ``once()`` has seen."""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone

__all__ = ["Delivery", "Handled", "OutboxEvent"]


class OutboxEvent(models.Model):
    """One published family event, written in the publisher's transaction.

    ``id`` is the event's own id (the payload's ``id``). ``payload`` is the
    whole event as JSON. ``subject_model``, ``subject_id`` and ``person_id``
    repeat what the payload says, so the admin can filter by them, and
    ``request_id`` is the id of the request or task that published it, so
    ``karni trace`` follows the event to its deliveries. This is a delivery
    log, not a source of truth: delivered rows are pruned after
    ``KARNI_EVENTS_RETENTION_DAYS``.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, db_index=True)
    version = models.PositiveSmallIntegerField(default=1)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    subject_model = models.CharField(max_length=200, blank=True, default="")
    subject_id = models.CharField(max_length=200, blank=True, default="")
    person_id = models.CharField(max_length=200, blank=True, default="")
    actor_id = models.CharField(max_length=200, blank=True, default="")
    request_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    payload = models.JSONField(default=dict)

    class Meta:
        ordering = ("-occurred_at",)
        verbose_name = "event"
        verbose_name_plural = "events"
        indexes = [
            models.Index(fields=["subject_model", "subject_id"], name="karni_outbox_subject"),
        ]

    def __str__(self) -> str:
        return f"{self.name} v{self.version} at {self.occurred_at:%Y-%m-%d %H:%M:%S}"

    @property
    def subject_ref(self) -> str:
        """``"app_label.model:id"`` of the subject, or ``""``."""
        return f"{self.subject_model}:{self.subject_id}" if self.subject_model else ""


class Delivery(models.Model):
    """One subscriber's copy of one event: pending, delivered or failed.

    Created with the event, in the publisher's transaction. ``attempts``
    counts the runs, ``next_attempt_at`` is when the next one is due (the
    sweep sends a pending delivery whose time has passed), and
    ``last_error`` keeps the newest failure. A delivery that failed
    ``KARNI_EVENTS_MAX_ATTEMPTS`` times is ``failed``: the admin lists it and
    its *Retry* action makes it pending again.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed"

    event = models.ForeignKey(OutboxEvent, on_delete=models.CASCADE, related_name="deliveries")
    subscriber = models.CharField(max_length=255)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    delivered_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Never by the event: an ordering through the foreign key joins the event's
        # table, and a row lock would then hold the event for every other delivery.
        ordering = ("created_at", "subscriber")
        verbose_name = "delivery"
        verbose_name_plural = "deliveries"
        constraints = [
            models.UniqueConstraint(
                fields=["event", "subscriber"], name="karni_outbox_one_delivery_per_subscriber"
            ),
        ]
        indexes = [
            models.Index(fields=["status", "next_attempt_at"], name="karni_outbox_due"),
        ]

    def __str__(self) -> str:
        return f"{self.subscriber} [{self.status}]"

    def retry(self) -> None:
        """Make a failed delivery pending again, due now (the admin's *Retry* action)."""
        self.status = self.Status.PENDING
        self.next_attempt_at = timezone.now()
        self.save(update_fields=["status", "next_attempt_at", "updated_at"])


class Handled(models.Model):
    """A ``(event, key)`` pair :func:`karni.events.once` has already said yes to."""

    event_id = models.UUIDField()
    key = models.CharField(max_length=200)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "handled key"
        verbose_name_plural = "handled keys"
        constraints = [
            models.UniqueConstraint(fields=["event_id", "key"], name="karni_outbox_once"),
        ]

    def __str__(self) -> str:
        return f"{self.key} for {self.event_id}"
