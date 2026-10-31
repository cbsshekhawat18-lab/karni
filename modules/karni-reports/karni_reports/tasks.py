"""The Celery task that renders a queued report.

``render_report`` claims the pending row (pending becomes rendering in one
UPDATE, so two workers never render the same row), renders it and stores the
file (:func:`karni_reports.services.render`). A failure is stored on the row
with status ``failed``. It is not retried: a broken template fails again, and
the next request or the admin's Regenerate action queues it once more.

Override / escape hatch: register a task of your own under another name that
calls :func:`karni_reports.services.render_queued`, and route it to the queue
you want with Celery's ``task_routes``.
"""

from __future__ import annotations

from celery import shared_task

from karni_reports import services

__all__ = ["render_report"]


@shared_task(name="karni_reports.tasks.render_report")
def render_report(report_pk: str) -> str:
    """Render the queued :class:`~karni_reports.models.GeneratedReport` ``report_pk``.

    Returns the row's status after the run, or ``"skipped"`` when it was no
    longer pending.
    """
    row = services.render_queued(report_pk)
    return row.status if row is not None else "skipped"
