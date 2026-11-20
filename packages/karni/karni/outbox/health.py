"""Experimental. The outbox's health check: failed deliveries and deliveries stuck waiting.

Add it to the checks ``/health/ready/`` runs::

    KARNI_HEALTH_CHECKS = [*KARNI_HEALTH_CHECKS, "karni.outbox.health.check_outbox"]

It fails while any delivery is ``failed`` (a person has to look: the admin's
*Deliveries*, filtered by status, and its *Retry* action) or while a pending
delivery is overdue by more than :data:`STUCK_AFTER` (no worker runs, or beat
does not run the sweep). Keep it out of ``KARNI_READYZ_CHECKS``: a
subscriber's failure should not take the web process out of rotation.
"""

from __future__ import annotations

import datetime as dt
from typing import Final

from django.utils import timezone

from karni.health.checks import CheckResult

__all__ = ["STUCK_AFTER", "check_outbox"]

#: A pending delivery overdue this long means nothing is delivering.
STUCK_AFTER: Final = dt.timedelta(minutes=10)


def check_outbox() -> CheckResult:
    """``(ok, detail)``: no failed delivery and none overdue by more than :data:`STUCK_AFTER`."""
    from karni.outbox.delivery import outbox_installed

    if not outbox_installed():
        return True, "karni.outbox is not installed"
    from karni.outbox.models import Delivery

    failed = Delivery.objects.filter(status=Delivery.Status.FAILED).count()
    stuck = Delivery.objects.filter(
        status=Delivery.Status.PENDING, next_attempt_at__lt=timezone.now() - STUCK_AFTER
    ).count()
    if failed or stuck:
        parts = []
        if failed:
            parts.append(f"{failed} failed (see Deliveries in the admin)")
        if stuck:
            minutes = int(STUCK_AFTER.total_seconds() // 60)
            parts.append(
                f"{stuck} waiting more than {minutes} minutes (is a worker and beat running?)"
            )
        return False, "event deliveries: " + ", ".join(parts)
    return True, "event deliveries up to date"
