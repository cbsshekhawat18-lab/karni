"""Built-in readiness checks for Karni projects.

A check is a zero-argument callable returning :data:`CheckResult`, an
``(ok, detail)`` tuple.  The readiness view
(:func:`karni.health.views.readiness`) discovers its checks through the
``KARNI_HEALTH_CHECKS`` setting — a list of dotted paths defaulting to
:data:`DEFAULT_HEALTH_CHECKS` — so a project can drop, reorder or replace any
of these, or register its own callables, by overriding that setting in its
``settings.py``.

Checks are allowed to raise: the readiness view converts any exception into a
failed check, so implementations here stay straightforward.
"""

from __future__ import annotations

from collections.abc import Callable

from celery import current_app
from django.conf import settings
from django.core.cache import cache
from django.db import connections

type CheckResult = tuple[bool, str]
"""Result of a health check: ``(ok, human-readable detail)``."""

type Check = Callable[[], CheckResult]
"""Signature every dotted path in ``KARNI_HEALTH_CHECKS`` must resolve to."""

DEFAULT_HEALTH_CHECKS: tuple[str, ...] = (
    "karni.health.checks.check_database",
    "karni.health.checks.check_cache",
    "karni.health.checks.check_celery",
)
"""Dotted paths used when the ``KARNI_HEALTH_CHECKS`` setting is absent."""

#: Cache key written and read back by :func:`check_cache`.
CACHE_KEY: str = "karni-health"


def check_database() -> CheckResult:
    """Verify the ``default`` database connection by executing ``SELECT 1``.

    Projects that need to probe a different database alias, or run a
    different query, should point ``KARNI_HEALTH_CHECKS`` at their own
    callable instead of (or in addition to) this one.
    """
    connection = connections["default"]
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        row = cursor.fetchone()
    if row is None or row[0] != 1:
        return False, f"unexpected result from SELECT 1: {row!r}"
    return True, "database responding"


def check_cache() -> CheckResult:
    """Round-trip a value through the ``default`` cache backend.

    Writes and reads back the key ``"karni-health"`` (Redis under Karni
    defaults).  To probe a different cache alias or key, register your own
    callable via the ``KARNI_HEALTH_CHECKS`` setting.
    """
    cache.set(CACHE_KEY, "ok", timeout=10)
    value = cache.get(CACHE_KEY)
    if value != "ok":
        return False, f"cache read-after-write returned {value!r}"
    return True, "cache responding"


def check_celery() -> CheckResult:
    """Ping Celery workers via the current app's control channel.

    Succeeds when at least one worker replies within
    ``KARNI_HEALTH_CELERY_TIMEOUT`` seconds (default ``1.0``), so the probe
    never hangs.  Override that setting to tune the deadline, or remove this
    entry from ``KARNI_HEALTH_CHECKS`` for projects that run no workers.
    """
    timeout = float(getattr(settings, "KARNI_HEALTH_CELERY_TIMEOUT", 1.0))
    replies = current_app.control.ping(timeout=timeout)
    if not replies:
        return False, f"no Celery worker replied within {timeout:g}s"
    return True, f"{len(replies)} worker(s) replied"
