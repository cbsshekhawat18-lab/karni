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

Experimental: ``/healthz`` and ``/readyz`` at the root, from ``*probe_urls`` (see
:mod:`karni.health.probe_urls`). ``/healthz`` is liveness. ``/readyz`` runs
``KARNI_READYZ_CHECKS`` (database, cache and the Celery broker by default) with
``KARNI_HEALTH_TIMEOUT`` seconds per check. Both are never cached, open before the terms are
accepted and left out of the request log (``KARNI_LOG_QUIET_PATHS``).

Escape hatches: override ``KARNI_HEALTH_CHECKS`` in the project's
``settings.py`` to add, drop, reorder or replace checks, and
``KARNI_HEALTH_CELERY_TIMEOUT`` to tune the Celery ping deadline.
"""

from karni.health.checks import (
    DEFAULT_HEALTH_CHECKS,
    DEFAULT_READY_CHECKS,
    Check,
    CheckResult,
    check_broker,
    check_cache,
    check_celery,
    check_database,
)
from karni.health.views import liveness, readiness, readyz

__all__ = [
    "DEFAULT_HEALTH_CHECKS",
    "DEFAULT_READY_CHECKS",
    "Check",
    "CheckResult",
    "check_broker",
    "check_cache",
    "check_celery",
    "check_database",
    "liveness",
    "readiness",
    "readyz",
]
