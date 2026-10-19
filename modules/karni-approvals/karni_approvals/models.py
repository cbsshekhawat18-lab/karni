"""The pending change and the decisions on it, both on ``karni.models.BaseModel``.

Both models are audited (``karni.audit``), so every proposal, approval and
rejection is history; the row itself gets its own history entry only when a
change is applied. This module ships an explicit ``admin.py`` (the approvals
queue) — see the README.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models
from karni.models import BaseModel

__all__ = ["Decision", "PendingChange"]


class PendingChange(BaseModel):
    """A change someone proposed that is waiting for a second person.

    ``changes`` is ``{field: [old, new]}`` as ``karni.audit`` would record it
    (relations by primary key, dates and decimals as strings); for a
    ``create`` every value is ``[None, new]``, for a ``delete`` it is empty.
    ``object_id`` is empty for a create (there is no row yet).
    """

    class Action(models.TextChoices):
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DELETE = "delete", "Delete"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        EXPIRED = "expired", "Expired"
        FAILED = "failed", "Failed"

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    object_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    action = models.CharField(max_length=10, choices=Action.choices)
    summary = models.CharField(max_length=200, blank=True, default="")
    changes = models.JSONField(default=dict, blank=True)
    maker = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    required = models.PositiveSmallIntegerField(default=1)
    approvals = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    escalated_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reason = models.TextField(blank=True, default="")

    class Meta(BaseModel.Meta):
        ordering: ClassVar[list[str]] = ["-created_at"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["status", "content_type"]),
            models.Index(fields=["content_type", "object_id"]),
        ]
        verbose_name = "pending change"

    class Karni:
        """Audited; ``approve`` and ``reject`` are permissions; makers own their proposals."""

        audit = True
        actions = ["approve", "reject"]
        owner_field = "maker"

    class APIMeta:
        """A read-only resource: decisions come through the approve/reject actions."""

        read_only = [
            "content_type",
            "object_id",
            "action",
            "summary",
            "changes",
            "maker",
            "status",
            "required",
            "approvals",
            "expires_at",
            "escalated_at",
            "resolved_at",
            "resolved_by",
            "reason",
        ]

    def __str__(self) -> str:
        return f"{self.get_action_display()} {self.summary or self.object_id} ({self.status})"

    @property
    def model_class(self) -> type[models.Model] | None:
        return self.content_type.model_class()

    @property
    def is_pending(self) -> bool:
        return self.status == self.Status.PENDING

    @property
    def target(self) -> Any | None:
        """The row this change is about (``None`` for a create or a vanished row)."""
        model = self.model_class
        if model is None or not self.object_id:
            return None
        return model._base_manager.filter(pk=self.object_id).first()


class Decision(BaseModel):
    """One checker's verdict on one pending change, with the reason."""

    class Verdict(models.TextChoices):
        APPROVE = "approve", "Approved"
        REJECT = "reject", "Rejected"

    pending = models.ForeignKey(PendingChange, on_delete=models.CASCADE, related_name="decisions")
    checker = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    verdict = models.CharField(max_length=10, choices=Verdict.choices)
    reason = models.TextField(blank=True, default="")

    class Meta(BaseModel.Meta):
        ordering: ClassVar[list[str]] = ["created_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["pending", "checker"], name="karni_approvals_one_decision"
            )
        ]

    class Karni:
        audit = True

    class APIMeta:
        read_only = ["pending", "checker", "verdict", "reason"]

    class AdminMeta:
        exclude = True

    def __str__(self) -> str:
        return f"{self.verdict} by {self.checker_id} on {self.pending_id}"
