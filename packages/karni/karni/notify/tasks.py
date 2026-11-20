"""Celery task of the notifications contract: prune old notifications."""

from __future__ import annotations

from celery import shared_task

__all__ = ["prune"]


@shared_task(name="karni.notify.tasks.prune", ignore_result=True)
def prune(days: int | None = None) -> int:
    """Delete notifications older than ``KARNI_NOTIFY_RETENTION_DAYS`` (beat, daily)."""
    from karni.notify.services import prune as run

    return run(days)
