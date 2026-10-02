"""Karni production profile.

Applied by ``karni_settings()`` on top of :data:`karni.conf.base.BASE` when
the profile is ``"prod"`` (``DJANGO_ENV=prod``). Production means: debug off,
strict security headers (HSTS, secure cookies, SSL redirect behind a
TLS-terminating proxy such as Caddy) and machine-readable JSON structlog
output (``KARNI_JSON_LOGS = True`` — the actual ``LOGGING`` dict is built by
:func:`karni.conf.logging.build_logging` inside ``karni_settings()``).

Startup validation additionally requires a real ``SECRET_KEY`` and a
non-empty ``ALLOWED_HOSTS`` when ``DEBUG`` is False.

Override / escape hatch: every key obeys the same setdefault semantics as
``BASE`` — define it in your settings module before calling
``karni_settings()``, pass it as a keyword override, or assign it after the
call. ``DEBUG`` and ``ALLOWED_HOSTS`` also read the environment variables of
the same name. Behind a proxy that does not set ``X-Forwarded-Proto``,
override ``SECURE_PROXY_SSL_HEADER`` and ``SECURE_SSL_REDIRECT``.
"""

from __future__ import annotations

from typing import Any

from karni.conf.base import env

PROD: dict[str, Any] = {
    "DEBUG": env.bool("DEBUG", default=False),
    "ALLOWED_HOSTS": env.list("ALLOWED_HOSTS", default=[]),
    "KARNI_JSON_LOGS": True,
    # TLS terminates at the reverse proxy (Caddy in the Karni stack); trust
    # its X-Forwarded-Proto header and redirect any plain-HTTP request.
    "SECURE_PROXY_SSL_HEADER": ("HTTP_X_FORWARDED_PROTO", "https"),
    "SECURE_SSL_REDIRECT": True,
    "SECURE_HSTS_SECONDS": 31536000,
    "SECURE_HSTS_INCLUDE_SUBDOMAINS": True,
    "SECURE_HSTS_PRELOAD": True,
    "SECURE_CONTENT_TYPE_NOSNIFF": True,
    "SESSION_COOKIE_SECURE": True,
    "CSRF_COOKIE_SECURE": True,
    "X_FRAME_OPTIONS": "DENY",
    "SECURE_REFERRER_POLICY": "same-origin",
}
"""Production overrides merged over ``BASE`` for the ``"prod"`` profile."""
