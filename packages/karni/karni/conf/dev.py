"""Karni development profile.

Applied by ``karni_settings()`` on top of :data:`karni.conf.base.BASE` when
the profile is ``"dev"`` (the ``DJANGO_ENV`` default). Development means:
debug on, every host allowed, wide-open CORS, console email (unless
``EMAIL_URL`` names a mail server),
human-readable console structlog output (``KARNI_JSON_LOGS = False`` — the
actual ``LOGGING`` dict is built by
:func:`karni.conf.logging.build_logging` inside ``karni_settings()``), query
budgets that warn instead of raising (``KARNI_QUERY_BUDGET_MODE = "warn"``)
and the per-request query log (``KARNI_QUERY_LOG``), and uploads and static
files under the project (``MEDIA_ROOT = "data/media"``, ``STATIC_ROOT =
"data/static"``, read from the project root), so a run on the host stores
files without a ``/data`` folder, and broker reads that give up after
:data:`BROKER_SOCKET_TIMEOUT` seconds (``CELERY_BROKER_TRANSPORT_OPTIONS``),
so a stopping worker cannot wait for good on a Redis that does not answer.

Override / escape hatch: every key obeys the same setdefault semantics as
``BASE`` — define it in your settings module before calling
``karni_settings()``, pass it as a keyword override, or assign it after the
call. ``DEBUG`` and ``ALLOWED_HOSTS`` also read the environment variables of
the same name.
"""

from __future__ import annotations

from typing import Any

import environ

from karni.conf.base import env

CONSOLE_EMAIL = "django.core.mail.backends.console.EmailBackend"

#: Seconds a development process waits for the broker to answer a read. It is
#: longer than the 1 second BRPOP Celery's Redis transport polls with.
BROKER_SOCKET_TIMEOUT = 5


def console_email(reader: environ.Env) -> dict[str, str]:
    """Development prints mail to the console, unless ``EMAIL_URL`` names a mail server."""
    return {} if reader.str("EMAIL_URL", default="") else {"EMAIL_BACKEND": CONSOLE_EMAIL}


DEV: dict[str, Any] = {
    "DEBUG": env.bool("DEBUG", default=True),
    "ALLOWED_HOSTS": env.list("ALLOWED_HOSTS", default=["*"]),
    "CORS_ALLOW_ALL_ORIGINS": True,
    **console_email(env),
    "KARNI_JSON_LOGS": False,
    # Over-budget requests log the grouped duplicate report (never raise);
    # every request's query count, duplicates and time are logged.
    "KARNI_QUERY_BUDGET_MODE": env("KARNI_QUERY_BUDGET_MODE", default="warn"),
    "KARNI_QUERY_LOG": env.bool("KARNI_QUERY_LOG", default=True),
    # Uploads and collected static files under the project (data/ is git-ignored),
    # read from the project root. The container image sets /data/media and
    # /data/static, and production keeps BASE's /data defaults.
    "MEDIA_ROOT": env("MEDIA_ROOT", default="data/media"),
    "STATIC_ROOT": env("STATIC_ROOT", default="data/static"),
    # A read from the broker gives up after BROKER_SOCKET_TIMEOUT seconds. A
    # stopping worker reads the answer to its last BRPOP without a timeout of
    # its own, so a Redis that never sends it (one whose timers stalled, as a
    # long-running Redis on a Mac can) would hold the warm shutdown for good.
    # Production keeps Celery's default.
    "CELERY_BROKER_TRANSPORT_OPTIONS": {"socket_timeout": BROKER_SOCKET_TIMEOUT},
}
"""Development overrides merged over ``BASE`` for the ``"dev"`` profile."""
