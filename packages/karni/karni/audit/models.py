"""The change log: one row per captured change of an audited model instance."""

from __future__ import annotations

from typing import Any, ClassVar

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

__all__ = ["ChangeBatch", "ChangeLog", "ChangeLogQuerySet"]


class ChangeBatch(models.Model):
    """One operation that changed many rows at once — an import, a bulk action.

    Every :class:`ChangeLog` entry written while the batch is current
    (:func:`karni.audit.capture.change_batch`) points at it, so "which rows
    did this import touch" and "which import changed this row" are one query
    each. ``meta`` carries what the operation knows about itself (file name,
    counts, the job id). ``request_id`` is the id of the request (or task)
    that ran it (:mod:`karni.tracing`), so ``karni trace`` finds it.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    kind = models.CharField(max_length=32)
    label = models.CharField(max_length=200, blank=True, default="")
    meta = models.JSONField(default=dict, blank=True)
    request_id = models.CharField(max_length=128, blank=True, default="", db_index=True)

    class Meta:
        ordering = ("-timestamp", "-id")
        verbose_name = "change batch"
        verbose_name_plural = "change batches"

    def __str__(self) -> str:
        return f"{self.kind} {self.label or self.pk} at {self.timestamp:%Y-%m-%d %H:%M}"


class ChangeLogQuerySet(models.QuerySet["ChangeLog"]):
    def for_object(self, obj: models.Model) -> ChangeLogQuerySet:
        """Entries of one row, newest first."""
        return self.filter(
            content_type=ContentType.objects.get_for_model(obj, for_concrete_model=False),
            object_id=str(obj.pk),
        )

    def for_model(self, model: type[models.Model]) -> ChangeLogQuerySet:
        return self.filter(
            content_type=ContentType.objects.get_for_model(model, for_concrete_model=False)
        )


class ChangeLog(models.Model):
    """Who changed what, from what, to what — ``diff`` holds changed fields only.

    ``diff`` is ``{field: [old, new]}``; a redacted field carries
    ``["[redacted]", "[redacted]"]``. Relations are recorded by primary key,
    dates and decimals as strings, files by name. ``object_id`` is the row's
    primary key as text, so UUID and integer keys share one table.
    ``request_id`` is the id of the request or task that made the change
    (:mod:`karni.tracing`; ``""`` from a shell), so ``karni trace <id>`` lists
    every change one request made.
    """

    class Action(models.TextChoices):
        CREATE = "create", "Created"
        UPDATE = "update", "Updated"
        DELETE = "delete", "Deleted"
        RESTORE = "restore", "Restored"
        TRANSITION = "transition", "Transitioned"

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    object_id = models.CharField(max_length=64, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    action = models.CharField(max_length=10, choices=Action.choices)
    diff = models.JSONField(default=dict, blank=True)
    batch = models.ForeignKey(
        ChangeBatch, null=True, blank=True, on_delete=models.SET_NULL, related_name="entries"
    )
    request_id = models.CharField(max_length=128, blank=True, default="", db_index=True)

    objects: ClassVar[models.Manager[ChangeLog]] = ChangeLogQuerySet.as_manager()

    class Meta:
        ordering = ("-timestamp", "-id")
        indexes = [models.Index(fields=["content_type", "object_id", "-timestamp"])]
        verbose_name = "change"
        verbose_name_plural = "change log"

    def __str__(self) -> str:
        when = f"{self.timestamp:%Y-%m-%d %H:%M}"
        return f"{self.action} {self.content_type_id}:{self.object_id} at {when}"

    @property
    def fields_changed(self) -> list[str]:
        return sorted(self.diff) if isinstance(self.diff, dict) else []

    def visible_diff(self, user: Any) -> dict[str, Any]:
        """The diff without the fields ``Karni.field_roles`` hides from ``user`` (P3)."""
        from karni.accounts.visibility import hidden_fields

        model = self.content_type.model_class()
        if model is None or not isinstance(self.diff, dict):
            return {}
        hidden = hidden_fields(model, user)
        return {name: value for name, value in self.diff.items() if name not in hidden}
