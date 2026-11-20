"""Celery task of the timeline: prune old entries."""

from __future__ import annotations

from celery import shared_task

__all__ = ["prune"]


@shared_task(name="karni.timeline.tasks.prune", ignore_result=True)
def prune(days: int | None = None) -> int:
    """Delete entries older than ``KARNI_TIMELINE_RETENTION_DAYS`` (beat, daily)."""
    from karni.timeline.services import prune as run

    return run(days)
