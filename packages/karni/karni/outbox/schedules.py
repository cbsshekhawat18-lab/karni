"""The outbox's beat entries: the sweep every minute, pruning daily while retention is set."""

from __future__ import annotations

from django.conf import settings

from karni.schedule import every

every("1m", task="karni.outbox.tasks.sweep", name="karni-events-sweep")

if getattr(settings, "KARNI_EVENTS_RETENTION_DAYS", 30) is not None:
    every(days=1, task="karni.outbox.tasks.prune", name="karni-events-prune")
