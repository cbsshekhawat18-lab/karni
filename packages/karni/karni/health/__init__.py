"""Karni health endpoints: liveness and readiness probes for containerised deploys.

Mount the URLs in a project's ``config/urls.py``::

    from django.urls import include, path

    urlpatterns = [
        path("health/", include("karni.health.urls")),
    ]

which exposes:

- ``/health/`` — liveness: always ``200 {"status": "ok"}``, no I/O.
- ``/health/ready/`` — readiness: runs every check listed in the
  ``KARNI_HEALTH_CHECKS`` setting (dotted paths) and returns ``200`` only when
  all of them pass, ``503`` otherwise.

Escape hatches: override ``KARNI_HEALTH_CHECKS`` in the project's
``settings.py`` to add, drop, reorder or replace checks, and
``KARNI_HEALTH_CELERY_TIMEOUT`` to tune the Celery ping deadline.
"""

from karni.health.checks import (
    DEFAULT_HEALTH_CHECKS,
    Check,
    CheckResult,
    check_cache,
    check_celery,
    check_database,
)
from karni.health.views import liveness, readiness

__all__ = [
    "DEFAULT_HEALTH_CHECKS",
    "Check",
    "CheckResult",
    "check_cache",
    "check_celery",
    "check_database",
    "liveness",
    "readiness",
]
