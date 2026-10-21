"""Celery tasks for the schedule and queued-listener tests.

Plain ``@shared_task`` functions with default names (their dotted paths),
exactly what a project's ``<app>/tasks.py`` holds. Referenced by
``tests/testapp/schedules.py`` and ``tests/testapp/listeners.py``.
"""

from __future__ import annotations

from typing import Any

from celery import shared_task

#: Primary keys received by :func:`record_shelf_deleted`, in call order.
deleted_shelves: list[Any] = []


@shared_task
def tick(step: int = 1) -> int:
    """Echo ``step`` — the interval schedules' target."""
    return step


@shared_task
def nightly_report(days: int = 1) -> str:
    """The cron schedule's target."""
    return f"report for {days} day(s)"


@shared_task
def explode() -> None:
    """Always fails — proves ``karni_schedules --run`` reports task errors."""
    raise RuntimeError("scheduled task failed")


@shared_task
def record_shelf_deleted(pk: Any) -> None:
    """``queued(task)`` target: receives the deleted shelf's primary key."""
    deleted_shelves.append(pk)


@shared_task(bind=True, max_retries=3, default_retry_delay=0)
def flaky_mail(self: Any, to: str, fail_times: int = 1) -> str:
    """Fails ``fail_times`` times, then sends an email (tests/test_debug.py: retries keep ids)."""
    from django.core.mail import send_mail

    if self.request.retries < fail_times:
        raise self.retry(exc=RuntimeError("smtp is down"), countdown=0)
    send_mail("Your receipt", "Thanks.", None, [to])
    return "sent"


@shared_task
def broken_task(token: str) -> None:
    """Fails for good — the task failure snapshot (its ``token`` argument is redacted)."""
    raise ValueError("cannot process the order")
