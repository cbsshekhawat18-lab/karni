"""Requesting, rendering and keeping report files.

* :func:`request` finds the file of a report for one row at the current cache
  key, or queues a render (a Celery task on commit). A ready file is
  returned at once, without rendering.
* :func:`render` renders one :class:`~karni_reports.models.GeneratedReport`
  row inline: the task and ``manage.py karni_pregenerate`` call it. A failure
  is stored on the row (``REPORT007``), never raised.
* :func:`latest` is the row the last request for a report and row named:
  what the status and download endpoints answer about.

The cache key is the report's name, the row, the template version and the
data version (:mod:`karni_reports.versions`). After a render, files beyond
``KARNI_REPORTS_KEEP`` for that report and row are deleted.

Override / escape hatch: each step reads the report's own ``get_*`` methods
(:class:`karni_reports.report.Report`), and the task is
``karni_reports.tasks.render_report``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models import F, QuerySet
from django.utils import timezone

from karni_reports import conf
from karni_reports.models import GeneratedReport
from karni_reports.registry import get_report
from karni_reports.rendering import BASE_URL
from karni_reports.report import Report

__all__ = [
    "Key",
    "enqueue",
    "find",
    "key_for",
    "latest",
    "prune",
    "regenerate",
    "render",
    "render_queued",
    "request",
    "rows_of",
]

logger = logging.getLogger(__name__)

Status = GeneratedReport.Status
#: The code of a failed render, stored on the row and logged.
RENDER_FAILED = "REPORT007"
#: The statuses of a render that has not finished.
IN_FLIGHT = (Status.PENDING, Status.RENDERING)


@dataclass(frozen=True)
class Key:
    """Experimental. The cache key of one report of one row."""

    report: str
    content_type: ContentType
    object_id: str
    template: str
    template_version: str
    data_version: str

    def lookup(self) -> dict[str, Any]:
        return {
            "report": self.report,
            "content_type": self.content_type,
            "object_id": self.object_id,
            "template_version": self.template_version,
            "data_version": self.data_version,
        }


def key_for(report: Report, obj: Any, context: dict[str, Any] | None = None) -> Key:
    """The current cache key of ``report`` for ``obj`` (runs ``get_context`` once)."""
    if context is None:
        context = report.get_context(obj)
    return Key(
        report=report.name,
        content_type=ContentType.objects.get_for_model(report.get_model()),
        object_id=str(obj.pk),
        template=report.get_template_name(),
        template_version=report.get_template_version(),
        data_version=report.get_data_version(obj, context),
    )


def rows_of(report: Report, object_id: Any) -> QuerySet[GeneratedReport]:
    """Every generated report of ``report`` for the row ``object_id``, newest request first."""
    return GeneratedReport.objects.filter(
        report=report.name,
        content_type=ContentType.objects.get_for_model(report.get_model()),
        object_id=str(object_id),
    ).order_by("-requested_at", "-created_at")


def find(key: Key) -> GeneratedReport | None:
    """The row of ``key``, whatever its status."""
    return GeneratedReport.objects.filter(**key.lookup()).first()


def latest(report: Report, object_id: Any) -> GeneratedReport | None:
    """The row the last request for ``report`` and this row named, or ``None``."""
    return rows_of(report, object_id).first()


def _stuck(row: GeneratedReport) -> bool:
    timeout = int(conf.get("KARNI_REPORTS_RENDER_TIMEOUT"))
    return row.status in IN_FLIGHT and row.updated_at < timezone.now() - timedelta(seconds=timeout)


def request(report: Report, obj: Any, *, queue: bool = True) -> GeneratedReport:
    """Experimental. The report of ``obj`` at its current key: ready, or queued to render.

    A ready row is returned as it is, without rendering. A new key gets a
    pending row and a render queued on commit. A failed row, or one pending
    or rendering for longer than ``KARNI_REPORTS_RENDER_TIMEOUT`` seconds,
    is queued again. ``queue=False`` leaves the queuing to the caller.
    """
    key = key_for(report, obj)
    now = timezone.now()
    row = find(key)
    if row is None:
        try:
            with transaction.atomic():
                row = GeneratedReport.objects.create(
                    **key.lookup(), template=key.template, requested_at=now
                )
        except IntegrityError:  # another request created it a moment ago
            row = find(key)
            if row is None:  # pragma: no cover - deleted again in between
                raise
        else:
            if queue:
                enqueue(row)
            return row
    again = row.status == Status.FAILED or _stuck(row)
    if again:
        row.status, row.error = Status.PENDING, ""
    row.requested_at = now
    row.save(update_fields=["status", "error", "requested_at", "updated_at"])
    if again and queue:
        enqueue(row)
    return row


def enqueue(row: GeneratedReport) -> None:
    """Queue ``row``'s render on commit (``karni_reports.tasks.render_report``)."""
    from karni_reports.tasks import render_report

    pk = str(row.pk)
    transaction.on_commit(lambda: render_report.delay(pk))


def render_queued(pk: str) -> GeneratedReport | None:
    """The task's work: claim the pending row ``pk`` and render it (``None``: nothing to do)."""
    claimed = GeneratedReport.objects.filter(pk=pk, status=Status.PENDING).update(
        status=Status.RENDERING, updated_at=timezone.now()
    )
    if not claimed:
        return None  # rendered, failed or taken by another worker meanwhile
    row = GeneratedReport.objects.get(pk=pk)
    return render(row)


def render(
    row: GeneratedReport, *, report: Report | None = None, obj: Any = None
) -> GeneratedReport:
    """Experimental. Render ``row`` now and store the file. Returns the row that holds it.

    The context is read again, so the file holds the row as it is now. When
    the row changed since the request, the stored key follows the data the
    file holds. A failure is stored on the row with status ``failed``
    (``REPORT007``) and logged, never raised.
    """
    try:
        if report is None:
            report = get_report(row.report)
        if obj is None:
            obj = report.get_queryset().get(pk=row.object_id)
        context = report.get_context(obj)
        template_version = report.get_template_version()
        data_version = report.get_data_version(obj, context)
        html = report.render_html(obj, context)
        pdf = report.get_renderer().render(html, base_url=BASE_URL)
    except Exception as exc:  # noqa: BLE001 - stored on the row for the admin
        logger.warning(
            "%s: report %r of %s failed to render",
            RENDER_FAILED,
            row.report,
            row.object_id,
            exc_info=True,
        )
        row.status, row.error = Status.FAILED, f"{type(exc).__name__}: {exc}"[:4000]
        row.save(update_fields=["status", "error", "updated_at"])
        return row
    if (template_version, data_version) != (row.template_version, row.data_version):
        twin = (
            GeneratedReport.objects.filter(
                report=row.report,
                content_type_id=row.content_type_id,
                object_id=row.object_id,
                template_version=template_version,
                data_version=data_version,
            )
            .exclude(pk=row.pk)
            .first()
        )
        if twin is not None:  # another row already stands for what this file would hold
            row.hard_delete()
            return twin
        row.template_version, row.data_version = template_version, data_version
    old = row.file.name if row.file else ""
    filename = f"{row.object_id}-{data_version[:16]}.pdf"
    row.file.save(filename, ContentFile(pdf), save=False)
    row.size = len(pdf)
    row.status, row.error, row.rendered_at = Status.READY, "", timezone.now()
    row.save()
    if old and old != row.file.name:
        row.file.storage.delete(old)
    prune(row)
    return row


def _discard(row: GeneratedReport) -> None:
    if row.file:
        row.file.delete(save=False)
    row.hard_delete()


def prune(row: GeneratedReport) -> int:
    """Delete the files of the same report and row beyond ``KARNI_REPORTS_KEEP``.

    The newest ready files are kept (``row`` counts as one), failed rows
    older than ``row`` go, and a render still pending is never touched.
    Returns how many rows were deleted. ``KARNI_REPORTS_KEEP = 0`` keeps all.
    """
    keep = int(conf.get("KARNI_REPORTS_KEEP"))
    if keep <= 0:
        return 0
    others = (
        GeneratedReport.objects.filter(
            report=row.report, content_type_id=row.content_type_id, object_id=row.object_id
        )
        .exclude(pk=row.pk)
        .order_by(F("rendered_at").desc(nulls_last=True), "-created_at")
    )
    deleted = 0
    kept = 1
    for other in others:
        if other.status == Status.READY and kept < keep:
            kept += 1
            continue
        if other.status == Status.READY or (
            other.status == Status.FAILED and other.created_at <= row.created_at
        ):
            _discard(other)
            deleted += 1
    return deleted


def regenerate(rows: QuerySet[GeneratedReport]) -> int:
    """Queue every row in ``rows`` to render again (the admin's action). Returns the count."""
    count = 0
    for row in rows:
        row.status, row.error = Status.PENDING, ""
        row.save(update_fields=["status", "error", "updated_at"])
        enqueue(row)
        count += 1
    return count
