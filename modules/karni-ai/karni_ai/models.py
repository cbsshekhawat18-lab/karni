"""The usage log: one :class:`AICall` row per provider call."""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.db import models
from karni.models import BigIntBaseModel

__all__ = ["AICall"]


class AICall(BigIntBaseModel):
    """Experimental. One provider call: who, for which resource, which model, its tokens and cost.

    Written by :mod:`karni_ai.usage` for every call, the failed ones included
    (``status`` failed, ``error_code`` AI006 or AI007, with the tokens the
    provider still billed). ``cost`` is computed from ``KARNI_AI_PRICES`` at
    the time of the call, and is empty for a model the table does not name.
    The monthly budgets sum ``input_tokens + output_tokens`` of these rows.
    The admin shows them read-only. The table grows with use, hence the
    integer key.
    """

    class Source(models.TextChoices):
        TEXT = "text", "Text"
        URL = "url", "URL"
        PDF = "pdf", "PDF"

    class Status(models.TextChoices):
        OK = "ok", "OK"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    provider = models.CharField(max_length=50)
    model = models.CharField(max_length=200, blank=True, default="")
    resource = models.CharField(max_length=100)
    source = models.CharField(max_length=10, choices=Source.choices)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cost = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OK)
    error_code = models.CharField(max_length=10, blank=True, default="")
    import_job = models.ForeignKey(
        "karni_transfer.ImportJob",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta(BigIntBaseModel.Meta):
        ordering: ClassVar[list[str]] = ["-created_at"]
        verbose_name = "AI call"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["user", "created_at"], name="karni_ai_call_user_time"),
        ]

    class APIMeta:
        """Read through ``/api/ai/``: each user their own calls."""

        fields = [
            "id",
            "provider",
            "model",
            "resource",
            "source",
            "input_tokens",
            "output_tokens",
            "cost",
            "status",
            "error_code",
            "import_job",
            "created_at",
        ]

    def __str__(self) -> str:
        return f"{self.provider}/{self.model} for {self.resource} ({self.status})"

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens
