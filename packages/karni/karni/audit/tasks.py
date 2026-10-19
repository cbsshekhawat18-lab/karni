"""Celery tasks: the asynchronous write path and retention pruning."""

from __future__ import annotations

import datetime as dt
from typing import Any

from celery import shared_task
from django.conf import settings
from django.utils import timezone

__all__ = ["prune_change_logs", "record_change"]


@shared_task(name="karni.audit.tasks.record_change")
def record_change(payload: dict[str, Any]) -> None:
    """Write one entry (the ``KARNI_AUDIT_ASYNC`` path; history is then eventually consistent)."""
    from karni.audit.capture import write

    write(payload)


@shared_task(name="karni.audit.tasks.prune_change_logs")
def prune_change_logs(days: int | None = None) -> int:
    """Delete entries older than ``days`` (default ``KARNI_AUDIT_RETENTION_DAYS``).

    A no-op, returning 0, while retention is off (the setting is ``None``):
    the task is safe to schedule unconditionally. Projects with a legal
    retention requirement archive before pruning — see the docs.
    """
    window = days if days is not None else getattr(settings, "KARNI_AUDIT_RETENTION_DAYS", None)
    if window is None:
        return 0
    from karni.audit.models import ChangeLog

    cutoff = timezone.now() - dt.timedelta(days=int(window))
    deleted, _ = ChangeLog.objects.filter(timestamp__lt=cutoff).delete()
    return int(deleted)
