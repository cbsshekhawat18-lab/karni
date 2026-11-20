"""Celery tasks of the family events outbox: deliver one event, sweep, prune."""

from __future__ import annotations

from typing import Any

from celery import shared_task
from django.utils import timezone

__all__ = ["deliver", "prune", "sweep"]


@shared_task(name="karni.outbox.tasks.deliver", ignore_result=True)
def deliver(event_id: str) -> dict[str, Any]:
    """Run the due deliveries of one event, then queue the next retry, if any.

    With ``CELERY_TASK_ALWAYS_EAGER`` the retry is not queued (it would run at
    once, inside this call): the sweep or
    :func:`karni.testing.events.deliver_now` runs it.
    """
    from karni.outbox.delivery import deliver_event, dispatch

    report = deliver_event(event_id)
    if report.next_attempt_at is not None and not deliver.app.conf.task_always_eager:
        wait = (report.next_attempt_at - timezone.now()).total_seconds()
        dispatch(event_id, countdown=max(wait, 0.0))
    return report.as_dict()


@shared_task(name="karni.outbox.tasks.sweep", ignore_result=True)
def sweep() -> int:
    """Send every event with an overdue delivery again (beat, every minute)."""
    from karni.outbox.delivery import sweep as run

    return run()


@shared_task(name="karni.outbox.tasks.prune", ignore_result=True)
def prune(days: int | None = None) -> int:
    """Delete delivered events older than ``KARNI_EVENTS_RETENTION_DAYS`` (beat, daily)."""
    from karni.outbox.delivery import prune as run

    return run(days)
