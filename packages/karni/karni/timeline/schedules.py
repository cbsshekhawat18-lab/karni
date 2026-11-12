"""The timeline's beat entry: pruning daily while ``KARNI_TIMELINE_RETENTION_DAYS`` is set."""

from __future__ import annotations

from django.conf import settings

from karni.schedule import every

if getattr(settings, "KARNI_TIMELINE_RETENTION_DAYS", None) is not None:
    every(days=1, task="karni.timeline.tasks.prune", name="karni-timeline-prune")
