"""Karni development profile.

Applied by ``karni_settings()`` on top of :data:`karni.conf.base.BASE` when
the profile is ``"dev"`` (the ``DJANGO_ENV`` default). Development means:
debug on, every host allowed, wide-open CORS, console email,
human-readable console structlog output (``KARNI_JSON_LOGS = False`` — the
actual ``LOGGING`` dict is built by
:func:`karni.conf.logging.build_logging` inside ``karni_settings()``), query
budgets that warn instead of raising (``KARNI_QUERY_BUDGET_MODE = "warn"``)
and the per-request query log (``KARNI_QUERY_LOG``).

Override / escape hatch: every key obeys the same setdefault semantics as
``BASE`` — define it in your settings module before calling
``karni_settings()``, pass it as a keyword override, or assign it after the
call. ``DEBUG`` and ``ALLOWED_HOSTS`` also read the environment variables of
the same name.
"""

from __future__ import annotations

from typing import Any

from karni.conf.base import env

DEV: dict[str, Any] = {
    "DEBUG": env.bool("DEBUG", default=True),
    "ALLOWED_HOSTS": env.list("ALLOWED_HOSTS", default=["*"]),
    "CORS_ALLOW_ALL_ORIGINS": True,
    "EMAIL_BACKEND": "django.core.mail.backends.console.EmailBackend",
    "KARNI_JSON_LOGS": False,
    # Over-budget requests log the grouped duplicate report (never raise);
    # every request's query count, duplicates and time are logged.
    "KARNI_QUERY_BUDGET_MODE": env("KARNI_QUERY_BUDGET_MODE", default="warn"),
    "KARNI_QUERY_LOG": env.bool("KARNI_QUERY_LOG", default=True),
}
"""Development overrides merged over ``BASE`` for the ``"dev"`` profile."""
