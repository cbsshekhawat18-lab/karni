"""Celery tasks: notify the checkers, escalate, and the hourly sweep."""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

__all__ = ["notify_checkers", "notify_escalation", "sweep_pending"]

logger = logging.getLogger(__name__)


@shared_task(name="karni_approvals.tasks.notify_checkers")
def notify_checkers(pending_id: str) -> int:
    """Run the configured notifier for one pending change; returns its recipient count."""
    from karni_approvals.models import PendingChange
    from karni_approvals.notify import notifier

    fn = notifier()
    pending = (
        PendingChange.objects.filter(pk=pending_id).select_related("content_type", "maker").first()
    )
    if fn is None or pending is None or not pending.is_pending:
        return 0
    return int(fn(pending) or 0)


@shared_task(name="karni_approvals.tasks.notify_escalation")
def notify_escalation(pending_id: str) -> int:
    from karni_approvals.models import PendingChange
    from karni_approvals.notify import email_escalation

    pending = (
        PendingChange.objects.filter(pk=pending_id).select_related("content_type", "maker").first()
    )
    if pending is None or not pending.is_pending:
        return 0
    return email_escalation(pending)


@shared_task(name="karni_approvals.tasks.sweep_pending")
def sweep_pending() -> dict[str, Any]:
    """Expire or escalate overdue pending changes (scheduled hourly by ``schedules.py``)."""
    from karni_approvals.services import sweep

    counts = sweep()
    if counts["expired"] or counts["escalated"]:
        logger.info("karni_approvals: %(expired)d expired, %(escalated)d escalated", counts)
    return dict(counts)
