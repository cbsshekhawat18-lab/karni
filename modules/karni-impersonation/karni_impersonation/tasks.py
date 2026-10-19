"""Celery tasks: notify the target, and the hourly sweep that closes abandoned sessions."""

from __future__ import annotations

from celery import shared_task

__all__ = ["notify_target", "sweep_sessions"]


@shared_task(name="karni_impersonation.tasks.notify_target")
def notify_target(session_id: str) -> int:
    from karni_impersonation.models import ImpersonationSession
    from karni_impersonation.notify import email_target

    session = (
        ImpersonationSession.objects.filter(pk=session_id).select_related("actor", "target").first()
    )
    return email_target(session) if session is not None else 0


@shared_task(name="karni_impersonation.tasks.sweep_sessions")
def sweep_sessions() -> int:
    from karni_impersonation.services import sweep

    return sweep()
