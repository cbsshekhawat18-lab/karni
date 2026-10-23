"""Karni's deploy checks: what ``manage.py check --deploy`` and ``karni check --deploy`` report.

Each check is a Django system check registered with
``@register(Tags.security, deploy=True)``, so it runs only when a deploy
check is asked for, never on ``runserver`` or ``migrate``. Each has a code
(``karni.W510`` to ``karni.W519``) whose entry in :mod:`karni.errorcodes`
says why it matters and how to fix it. Run them with the production
environment, for example ``DJANGO_ENV=prod DEBUG=False SECRET_KEY=...``.

Several overlap Django's own deploy warnings. Karni's say which environment
variable or setting fixes the problem in a Karni project, and
``karni check --deploy`` hides the Django warning a Karni one covers
(:data:`SUPERSEDES`), so each problem is printed once.

Override / escape hatch: silence a check you accept on purpose with
``SILENCED_SYSTEM_CHECKS += ["karni.W516"]``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, Final
from urllib.parse import urlsplit

from django.conf import settings
from django.core import checks
from django.core.checks import Tags, register

from karni.errorcodes import get as registry_entry
from karni.exceptions import check_warning

__all__ = ["SUPERSEDES", "weak_secret_key"]

#: Django's deploy warnings each Karni check covers. ``karni check --deploy``
#: silences them while the Karni check itself is not silenced.
SUPERSEDES: Final[dict[str, tuple[str, ...]]] = {
    "karni.W510": ("security.W018",),
    "karni.W511": ("security.W009",),
    "karni.W512": ("security.W020",),
    "karni.W514": ("security.W004",),
    "karni.W515": ("security.W010", "security.W011", "security.W012", "security.W016"),
}

#: Django's own strength rule for ``SECRET_KEY`` (``security.W009``): this long, this varied.
SECRET_KEY_MIN_LENGTH: Final = 50
SECRET_KEY_MIN_UNIQUE: Final = 5
_PROBE_ORIGIN: Final = "https://attacker.invalid"


def _fix(code: str) -> str:
    entry = registry_entry(code)
    return entry.fix if entry is not None else "See the linked page."


def _warn(code: str, message: str, obj: Any = None) -> list[checks.CheckMessage]:
    return [check_warning(code, message, hint=_fix(code), obj=obj)]


def weak_secret_key(key: Any) -> str | None:
    """Why ``key`` is not fit for production, or ``None`` when it is."""
    from karni.conf.base import INSECURE_SECRET_KEY

    text = str(key or "")
    if not text:
        return "SECRET_KEY is empty"
    if text == INSECURE_SECRET_KEY or "insecure" in text.lower():
        return "SECRET_KEY is a development key"
    if len(text) < SECRET_KEY_MIN_LENGTH:
        return f"SECRET_KEY has {len(text)} characters, fewer than {SECRET_KEY_MIN_LENGTH}"
    if len(set(text)) < SECRET_KEY_MIN_UNIQUE:
        return f"SECRET_KEY uses fewer than {SECRET_KEY_MIN_UNIQUE} different characters"
    return None


@register(Tags.security, deploy=True)
def check_debug(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.W510: ``DEBUG`` is on."""
    if not settings.DEBUG:
        return []
    return _warn(
        "W510",
        "DEBUG is True: an error page shows settings, code and the request to anyone who "
        "triggers it.",
    )


@register(Tags.security, deploy=True)
def check_secret_key(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.W511: ``SECRET_KEY`` is the scaffold's, or too short or too plain."""
    problem = weak_secret_key(getattr(settings, "SECRET_KEY", ""))
    if problem is None:
        return []
    return _warn("W511", f"{problem}: sessions, password resets and signed values can be forged.")


@register(Tags.security, deploy=True)
def check_allowed_hosts(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.W512: ``ALLOWED_HOSTS`` is empty or allows every host."""
    hosts = [str(host) for host in getattr(settings, "ALLOWED_HOSTS", None) or []]
    if not hosts:
        return _warn("W512", "ALLOWED_HOSTS is empty: the site answers no host name.")
    if "*" in hosts:
        return _warn(
            "W512",
            "ALLOWED_HOSTS contains '*': any Host header is accepted, so password-reset and "
            "verification links can be made to point at another site.",
        )
    return []


def _bad_origins(origins: Iterable[str]) -> list[str]:
    bad: list[str] = []
    for origin in origins:
        parts = urlsplit(origin)
        host = parts.hostname or ""
        if parts.scheme != "https" or not host or host == "*" or parts.netloc.startswith("*:"):
            bad.append(origin)
    return bad


@register(Tags.security, deploy=True)
def check_csrf_trusted_origins(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.W513: ``CSRF_TRUSTED_ORIGINS`` is empty, a wildcard, or plain http."""
    origins = [str(origin) for origin in getattr(settings, "CSRF_TRUSTED_ORIGINS", None) or []]
    if not origins:
        return _warn(
            "W513",
            "CSRF_TRUSTED_ORIGINS is empty: no https origin of the site is named, so a "
            "form or a session-mode frontend behind a proxy fails its CSRF check.",
        )
    bad = _bad_origins(origins)
    if bad:
        return _warn(
            "W513",
            f"CSRF_TRUSTED_ORIGINS has {', '.join(repr(o) for o in bad)}: each entry must be "
            "an https:// origin with a real host name, not a wildcard or plain http.",
        )
    return []


@register(Tags.security, deploy=True)
def check_hsts(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.W514: HSTS is off (``SECURE_HSTS_SECONDS`` is 0)."""
    seconds = getattr(settings, "SECURE_HSTS_SECONDS", 0) or 0
    if seconds > 0:
        return []
    return _warn(
        "W514",
        "SECURE_HSTS_SECONDS is 0: browsers may still reach the site over plain http, "
        "where a network attacker can read and change the traffic.",
    )


@register(Tags.security, deploy=True)
def check_secure_cookies(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.W515: the session or CSRF cookie may travel over plain http."""
    off = [
        name
        for name in ("SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE")
        if not getattr(settings, name, False)
    ]
    if not off:
        return []
    return _warn(
        "W515",
        f"{' and '.join(off)} {'is' if len(off) == 1 else 'are'} False: the cookie is sent "
        "over plain http too, where it can be read.",
    )


@register(Tags.security, deploy=True)
def check_admin_path(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.W516: the admin answers at ``/admin/``."""
    from django.urls import NoReverseMatch, reverse

    try:
        index = reverse("admin:index")
    except NoReverseMatch:
        return []
    if index.rstrip("/").rsplit("/", 1)[-1] != "admin":
        return []
    return _warn(
        "W516",
        f"The admin login is at {index}, the first path scanners try. Every password "
        "guess there costs an attacker nothing.",
    )


def _allows_any_origin(regexes: Iterable[Any]) -> bool:
    for pattern in regexes:
        try:
            if re.match(pattern, _PROBE_ORIGIN):
                return True
        except (re.error, TypeError):
            continue
    return False


@register(Tags.security, deploy=True)
def check_cors(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.W517: CORS lets every origin call the API."""
    allowed = [str(origin) for origin in getattr(settings, "CORS_ALLOWED_ORIGINS", None) or []]
    wildcard = (
        bool(getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False))
        or bool(getattr(settings, "CORS_ORIGIN_ALLOW_ALL", False))
        or "*" in allowed
        or _allows_any_origin(getattr(settings, "CORS_ALLOWED_ORIGIN_REGEXES", None) or [])
    )
    if not wildcard:
        return []
    credentials = bool(getattr(settings, "CORS_ALLOW_CREDENTIALS", False))
    reach = (
        "any site can call the API with the visitor's cookies"
        if credentials
        else "any site can call the API from a visitor's browser"
    )
    return _warn("W517", f"CORS allows every origin: {reach}.")


def _csp_middleware_installed() -> bool:
    from django.utils.module_loading import import_string

    from karni.security.headers import SecurityHeadersMiddleware

    for path in getattr(settings, "MIDDLEWARE", None) or []:
        try:
            middleware = import_string(str(path))
        except ImportError:
            continue
        if isinstance(middleware, type) and issubclass(middleware, SecurityHeadersMiddleware):
            return True
    return False


@register(Tags.security, deploy=True)
def check_csp_present(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.W518: no enforced Content-Security-Policy."""
    from karni.security.headers import csp_header_name

    if not _csp_middleware_installed():
        return _warn(
            "W518",
            "karni.security.SecurityHeadersMiddleware is not in MIDDLEWARE: responses carry "
            "no Content-Security-Policy.",
        )
    if getattr(settings, "KARNI_CSP", {}) is None:
        return _warn("W518", "KARNI_CSP is None: responses carry no Content-Security-Policy.")
    if csp_header_name().endswith("Report-Only"):
        return _warn(
            "W518",
            "The Content-Security-Policy is report-only (KARNI_CSP_REPORT_ONLY, or DEBUG): "
            "the browser reports what it would block and blocks nothing.",
        )
    return []


_WEAK_SCRIPT_SOURCES: Final = frozenset({"*", "'unsafe-eval'", "http:", "https:", "data:"})


@register(Tags.security, deploy=True)
def check_csp_scripts(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.W519: the site-wide policy lets scripts run from anywhere or from the page itself."""
    from karni.security.headers import csp_directives

    if getattr(settings, "KARNI_CSP", {}) is None:
        return []  # karni.W518 says so
    directives = csp_directives() or {}
    sources = directives.get("script-src", directives.get("default-src"))
    if sources is None:
        return _warn("W519", "The Content-Security-Policy has neither script-src nor default-src.")
    weak = [source for source in sources if source in _WEAK_SCRIPT_SOURCES]
    pinned = any(source.startswith(("'nonce-", "'sha")) for source in sources)
    if "'unsafe-inline'" in sources and not pinned:
        weak.append("'unsafe-inline'")
    if not weak:
        return []
    return _warn(
        "W519",
        f"script-src allows {' '.join(weak)}: an injected script would run, which is what "
        "the policy is there to stop.",
    )
