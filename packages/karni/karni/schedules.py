"""Karni's own schedule: the daily full flush of the API response cache.

Declared only while ``KARNI_API_CACHE`` is on and ``KARNI_API_CACHE_FLUSH``
names a time (``"03:30"``, or ``"03:30 Europe/Paris"`` for a timezone other
than Celery's). Off by default. ``CELERY_BEAT_SCHEDULE`` with the name
``karni-flush-api-cache`` wins over it, like any declared schedule.
"""

from __future__ import annotations

from django.conf import settings

from karni.api.caching import FLUSH_SCHEDULE, FLUSH_TASK, flush_schedule, flush_time
from karni.schedule import Schedule, registry

_when = flush_time()
if getattr(settings, "KARNI_API_CACHE", False) and _when is not None:
    registry.add(
        Schedule(
            name=FLUSH_SCHEDULE,
            task=FLUSH_TASK,
            schedule=flush_schedule(_when),
            timing=_when.describe(),
            source=__name__,
        )
    )
