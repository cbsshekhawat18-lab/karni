"""The outbox in the admin: events with their deliveries, failed deliveries, and Retry.

Nothing here is edited by hand. *Events* lists every published event, newest
first, with how many of its deliveries are pending, delivered and failed.
*Deliveries* lists one row per subscriber and event, filtered by status: the
failed ones are what the health check counts. Its *Retry* action makes the
selected failed or pending deliveries due now and sends their events.
"""

from __future__ import annotations

from typing import Any

from django.contrib import admin, messages
from django.db import models
from django.db.models import Count, Q
from django.http import HttpRequest
from unfold.admin import TabularInline

from karni.admin import KarniModelAdmin
from karni.outbox.models import Delivery, OutboxEvent

__all__ = ["DeliveryAdmin", "DeliveryInline", "OutboxEventAdmin"]


class _ReadOnly:
    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


class DeliveryInline(_ReadOnly, TabularInline):  # type: ignore[misc]
    """The event's deliveries on its page, one per subscriber."""

    model = Delivery
    extra = 0
    fields = ("subscriber", "status", "attempts", "next_attempt_at", "delivered_at")
    readonly_fields = fields
    can_delete = False
    show_change_link = True


@admin.register(OutboxEvent)
class OutboxEventAdmin(_ReadOnly, KarniModelAdmin):  # type: ignore[misc]
    """Every published event, newest first, with its deliveries by status."""

    list_display = ("name", "version", "occurred_at", "subject", "deliveries_summary")
    list_filter = ("name", "deliveries__status")
    search_fields = ("=id", "name", "subject_id", "person_id", "request_id")
    readonly_fields = (
        "id",
        "name",
        "version",
        "occurred_at",
        "subject_model",
        "subject_id",
        "person_id",
        "actor_id",
        "request_id",
        "payload",
    )
    date_hierarchy = "occurred_at"
    ordering = ("-occurred_at",)
    inlines = [DeliveryInline]

    def get_queryset(self, request: HttpRequest) -> models.QuerySet[OutboxEvent]:
        return (
            super()
            .get_queryset(request)
            .annotate(
                pending=Count("deliveries", filter=Q(deliveries__status=Delivery.Status.PENDING)),
                delivered=Count(
                    "deliveries", filter=Q(deliveries__status=Delivery.Status.DELIVERED)
                ),
                failed=Count("deliveries", filter=Q(deliveries__status=Delivery.Status.FAILED)),
            )
        )

    @admin.display(description="Subject", ordering="subject_model")
    def subject(self, obj: OutboxEvent) -> str:
        return obj.subject_ref or "-"

    @admin.display(description="Deliveries")
    def deliveries_summary(self, obj: OutboxEvent) -> str:
        counts = [
            (getattr(obj, "delivered", 0), "delivered"),
            (getattr(obj, "pending", 0), "pending"),
            (getattr(obj, "failed", 0), "failed"),
        ]
        parts = [f"{count} {label}" for count, label in counts if count]
        return ", ".join(parts) or "no subscribers"


@admin.register(Delivery)
class DeliveryAdmin(_ReadOnly, KarniModelAdmin):  # type: ignore[misc]
    """One row per subscriber and event: failed ones first to look at, and Retry."""

    list_display = ("subscriber", "event_name", "status", "attempts", "next_attempt_at")
    list_filter = ("status", "subscriber")
    search_fields = ("subscriber", "event__name", "=event__id", "last_error")
    readonly_fields = (
        "event",
        "subscriber",
        "status",
        "attempts",
        "next_attempt_at",
        "delivered_at",
        "last_error",
        "created_at",
        "updated_at",
    )
    list_select_related = ("event",)
    ordering = ("-created_at",)
    actions = ["retry"]

    @admin.display(description="Event", ordering="event__name")
    def event_name(self, obj: Delivery) -> str:
        return obj.event.name

    def has_retry_permission(self, request: HttpRequest) -> bool:
        user = request.user
        return bool(user.is_superuser or user.has_perm("karni_outbox.change_delivery"))

    @admin.action(description="Retry selected deliveries now", permissions=["retry"])
    def retry(self, request: HttpRequest, queryset: models.QuerySet[Delivery]) -> None:
        """Make the selected failed or pending deliveries due now and send their events."""
        from karni.outbox.delivery import dispatch

        chosen = queryset.exclude(status=Delivery.Status.DELIVERED)
        events = sorted({str(pk) for pk in chosen.values_list("event_id", flat=True)})
        for delivery in chosen:
            delivery.retry()
        for event_id in events:
            dispatch(event_id)
        self.message_user(
            request,
            f"{len(events)} event(s) sent again. Delivered rows were left as they were.",
            messages.SUCCESS,
        )
