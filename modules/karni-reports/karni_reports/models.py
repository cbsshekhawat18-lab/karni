"""The generated report: one PDF of one row, at one template and data version."""

from __future__ import annotations

from typing import Any, ClassVar

from django.contrib.contenttypes.models import ContentType
from django.core.files.storage import Storage
from django.db import models
from django.utils import timezone
from karni.models import BaseModel

from karni_reports import conf

__all__ = ["GeneratedReport", "report_file_name", "reports_storage"]


def reports_storage() -> Storage:
    """The storage the files are saved to: the ``KARNI_REPORTS_STORAGE`` alias."""
    from django.core.files.storage import storages

    return storages[conf.get("KARNI_REPORTS_STORAGE")]


def report_file_name(instance: GeneratedReport, filename: str) -> str:
    """``<KARNI_REPORTS_DIRECTORY>/<report>/<filename>``: where a rendered file is saved."""
    directory = str(conf.get("KARNI_REPORTS_DIRECTORY")).strip("/")
    return f"{directory}/{instance.report}/{filename}"


class GeneratedReport(BaseModel):
    """Experimental. One rendered PDF: a report of one row, at one template and data version.

    The cache key is the report's name, the row (``content_type`` and
    ``object_id``), ``template_version`` (a hash of the template's source, the
    templates it extends or includes, and the render options) and
    ``data_version`` (a hash of the context the report's ``get_context``
    returns). A request whose key has a ready row is served that row's file.
    ``object_id`` is text, so rows with UUID and integer keys both fit.
    ``requested_at`` moves on every request that names the row, so the
    status and the download answer about the last one.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RENDERING = "rendering", "Rendering"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    report = models.CharField(max_length=64)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    object_id = models.CharField(max_length=64)
    template = models.CharField(max_length=255)
    template_version = models.CharField(max_length=64)
    data_version = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    file = models.FileField(
        upload_to=report_file_name, storage=reports_storage, max_length=255, blank=True
    )
    size = models.PositiveBigIntegerField(default=0)
    error = models.TextField(blank=True, default="")
    rendered_at = models.DateTimeField(null=True, blank=True)
    requested_at = models.DateTimeField(default=timezone.now)

    class Meta(BaseModel.Meta):
        ordering: ClassVar[list[str]] = ["-created_at"]
        verbose_name = "generated report"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["report", "content_type", "object_id", "template_version", "data_version"],
                condition=models.Q(deleted_at__isnull=True),
                name="karni_reports_one_file_per_key",
            )
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["report", "content_type", "object_id", "-requested_at"],
                name="karni_reports_by_row",
            ),
            # GeneratedReportViewSet filters by it (?status=), karni.W967.
            models.Index(fields=["status"], name="karni_reports_by_status"),
        ]

    def __str__(self) -> str:
        return f"{self.report} of {self.content_type_id}:{self.object_id} ({self.status})"

    @property
    def is_ready(self) -> bool:
        return self.status == self.Status.READY and bool(self.file)

    def target_model(self) -> type[models.Model] | None:
        """The model of the row this report prints, or ``None`` when it no longer exists."""
        found: Any = self.content_type.model_class()
        return found
