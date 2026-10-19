"""The impersonation session record, on ``karni.models.BaseModel`` and audited."""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.db import models
from django.utils import timezone
from karni.models import BaseModel

__all__ = ["ImpersonationSession"]


class ImpersonationSession(BaseModel):
    """Who acted as whom, from when to when, why, and the audit batch every write joined.

    ``batch_id`` is the ``karni.audit`` ``ChangeBatch`` (kind ``impersonation``,
    actor = the impersonator) that every change made during the session points
    at — the row's own history names the target as its actor, the batch names
    the impersonator. The record is itself audited.
    """

    class EndReason(models.TextChoices):
        STOPPED = "stopped", "Stopped by the impersonator"
        EXPIRED = "expired", "Reached the time limit"
        LOGOUT = "logout", "The impersonator logged out"
        SWEPT = "swept", "Closed by the hourly sweep"

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    target = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    reason = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=10, choices=EndReason.choices, blank=True, default="")
    ip = models.CharField(max_length=64, blank=True, default="")
    user_agent = models.CharField(max_length=255, blank=True, default="")
    batch_id = models.BigIntegerField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        ordering: ClassVar[list[str]] = ["-started_at"]
        verbose_name = "impersonation session"

    class Karni:
        """Audited; ``impersonate`` is the permission the module is gated on."""

        audit = True
        actions = ["impersonate"]

    class APIMeta:
        read_only = [
            "actor",
            "target",
            "reason",
            "started_at",
            "expires_at",
            "ended_at",
            "end_reason",
            "ip",
            "user_agent",
            "batch_id",
        ]

    class AdminMeta:
        exclude = True  # the module ships an explicit, read-only admin

    def __str__(self) -> str:
        return f"{self.actor_id} as {self.target_id} from {self.started_at:%Y-%m-%d %H:%M}"

    @property
    def is_active(self) -> bool:
        return self.ended_at is None and self.expires_at > timezone.now()

    @property
    def is_expired(self) -> bool:
        return self.ended_at is None and self.expires_at <= timezone.now()
