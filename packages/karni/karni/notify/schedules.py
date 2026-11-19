"""The notifications' beat entry: pruning daily while ``KARNI_NOTIFY_RETENTION_DAYS`` is set."""

from __future__ import annotations

from django.conf import settings

from karni.schedule import every

if getattr(settings, "KARNI_NOTIFY_RETENTION_DAYS", None) is not None:
    every(days=1, task="karni.notify.tasks.prune", name="karni-notify-prune")
