"""Daily pruning, declared only when ``KARNI_AUDIT_RETENTION_DAYS`` is set (off by default)."""

from __future__ import annotations

from django.conf import settings

from karni.schedule import every

if getattr(settings, "KARNI_AUDIT_RETENTION_DAYS", None) is not None:
    every(days=1, task="karni.audit.tasks.prune_change_logs", name="karni-prune-change-logs")
