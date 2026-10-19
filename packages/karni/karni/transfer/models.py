"""The import job and the remembered column mappings."""

from __future__ import annotations

from typing import Any, ClassVar

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models

from karni.exceptions import KarniLookupError
from karni.models import BaseModel

__all__ = ["ColumnMapping", "ImportJob"]


class ImportJob(BaseModel):
    """One uploaded file on its way into one model: mapped, previewed, committed.

    The file lives in the default storage (so a Celery worker can read it);
    ``columns`` are its headers, ``mapping`` is header → field name (``""``
    ignores a column), ``result`` and ``problems`` are what the last run
    found, ``batch_id`` is the ``karni.audit`` batch a commit wrote.
    ``created_by`` (from ``BaseModel``) is the person importing.
    """

    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        PREVIEWING = "previewing", "Previewing"
        PREVIEWED = "previewed", "Previewed"
        COMMITTING = "committing", "Committing"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    file = models.FileField(upload_to="karni/imports/%Y/%m/")
    original_name = models.CharField(max_length=255)
    format = models.CharField(max_length=8)
    columns = models.JSONField(default=list, blank=True)
    mapping = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.UPLOADED)
    rows_total = models.PositiveIntegerField(default=0)
    rows_done = models.PositiveIntegerField(default=0)
    result = models.JSONField(null=True, blank=True)
    problems = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True, default="")
    batch_id = models.BigIntegerField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        ordering: ClassVar[list[str]] = ["-created_at"]
        verbose_name = "import job"

    class AdminMeta:
        """Jobs are read in the admin, never edited by hand."""

        list_display = ["original_name", "content_type", "status", "rows_total", "created_at"]
        list_filter = ["status", "content_type"]
        read_only = [
            "content_type",
            "file",
            "original_name",
            "format",
            "columns",
            "mapping",
            "status",
            "rows_total",
            "rows_done",
            "result",
            "problems",
            "error",
            "batch_id",
        ]

    def __str__(self) -> str:
        return f"{self.original_name} → {self.content_type_id} ({self.status})"

    @property
    def model_class(self) -> type[models.Model]:
        found = self.content_type.model_class()
        if found is None:  # pragma: no cover - a job for a model that no longer exists
            raise KarniLookupError(
                f"import job {self.pk}: model {self.content_type_id} no longer exists.",
                code="E801",
            )
        return found


class ColumnMapping(BaseModel):
    """The last column → field mapping a user confirmed for a model.

    Remembered so the second import of the same spreadsheet is one click.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    mapping = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["user", "content_type"], name="karni_columnmapping_user_model"
            )
        ]

    class AdminMeta:
        exclude = True

    def __str__(self) -> str:
        return f"mapping of {self.user_id} for {self.content_type_id}"

    @classmethod
    def remembered(cls, user: Any, model: type[models.Model]) -> dict[str, str]:
        """The mapping ``user`` last used for ``model`` (``{}`` when none)."""
        if user is None or not getattr(user, "is_authenticated", False):
            return {}
        found = cls.objects.filter(
            user=user, content_type=ContentType.objects.get_for_model(model)
        ).first()
        mapping = found.mapping if found is not None else {}
        return dict(mapping) if isinstance(mapping, dict) else {}

    @classmethod
    def remember(cls, user: Any, model: type[models.Model], mapping: dict[str, str]) -> None:
        if user is None or not getattr(user, "is_authenticated", False):
            return
        cls.objects.update_or_create(
            user=user,
            content_type=ContentType.objects.get_for_model(model),
            defaults={"mapping": dict(mapping)},
        )
