"""Liveness and readiness views for Karni projects.

Both views are plain Django function views so they work under WSGI and ASGI
alike and need no DRF machinery.  The readiness view is exception-proof by
design: a misbehaving or missing check becomes a failed entry in the JSON
payload, never a 500.

Escape hatches: the ``KARNI_HEALTH_CHECKS`` setting (list of dotted paths)
controls which checks run, and projects may mount these views under any URL
prefix — or route to their own views entirely — via their URLconf.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.db import connections
from django.http import HttpRequest, JsonResponse
from django.utils.module_loading import import_string
from django.views.decorators.cache import never_cache

from karni.health.checks import DEFAULT_HEALTH_CHECKS, DEFAULT_READY_CHECKS

#: Seconds a check may take before it counts as failed (``KARNI_HEALTH_TIMEOUT``).
DEFAULT_TIMEOUT: float = 3.0


def probe(view: Callable[..., Any]) -> Callable[..., Any]:
    """Experimental. Mark ``view`` as a probe: never cached, open before the terms are accepted.

    The terms gate (``karni.accounts.terms``) leaves a view with this mark alone
    wherever ``KARNI_TERMS["paths"]`` reaches, and ``never_cache`` keeps a proxy
    or a browser from answering for the process. Probes are plain Django views,
    so DRF's throttles never see them, and ``KARNI_LOG_QUIET_PATHS`` keeps the
    request log quiet for them.
    """
    wrapped = never_cache(view)
    wrapped.karni_probe = True  # type: ignore[attr-defined]
    return wrapped


@probe
def liveness(request: HttpRequest) -> JsonResponse:
    """Liveness probe: return ``200 {"status": "ok"}`` without touching I/O.

    Answers "is the process up?" only; dependency health belongs to
    :func:`readiness`.  Override by routing your own view in the project's
    URLconf instead of including ``karni.health.urls``.
    """
    return JsonResponse({"status": "ok"})


@probe
def readiness(request: HttpRequest) -> JsonResponse:
    """Readiness probe: run every check in ``KARNI_HEALTH_CHECKS``.

    Each entry is a dotted path (resolved with
    ``django.utils.module_loading.import_string``) to a zero-argument
    callable returning ``(ok, detail)``.  The response is::

        {"status": "ok" | "fail", "failing": [name, ...],
         "checks": {name: {"ok": bool, "detail": str}, ...}}

    with HTTP 200 when every check passes and 503 otherwise.  A check's name
    is its dotted path's final segment with any ``check_`` prefix stripped.
    Any exception raised while importing or running a check — including a bad
    dotted path — is reported as that check failing with the exception text
    as its detail; this view never raises.

    Override the check list per project via the ``KARNI_HEALTH_CHECKS``
    setting; when it is unset, :data:`karni.health.checks.DEFAULT_HEALTH_CHECKS`
    (database, cache, Celery) is used.
    """
    return _report("KARNI_HEALTH_CHECKS", DEFAULT_HEALTH_CHECKS)


@probe
def readyz(request: HttpRequest) -> JsonResponse:
    """Experimental. ``GET /readyz``: the database, the cache and the Celery broker.

    The same answer as :func:`readiness` over the checks in ``KARNI_READYZ_CHECKS``
    (default :data:`karni.health.checks.DEFAULT_READY_CHECKS`). The Celery check
    here reaches the broker only, so a web process is ready without a worker.
    Each check gets ``KARNI_HEALTH_TIMEOUT`` seconds (default 3). A failure is
    503 and ``"failing"`` names the checks that failed::

        {"status": "fail", "failing": ["cache"],
         "checks": {"database": {"ok": true, "detail": "database responding"},
                    "cache": {"ok": false, "detail": "Connection refused"},
                    "broker": {"ok": true, "detail": "broker responding"}}}
    """
    return _report("KARNI_READYZ_CHECKS", DEFAULT_READY_CHECKS)


def _report(setting: str, default: tuple[str, ...]) -> JsonResponse:
    """Run the checks the setting lists and build the JSON answer. Never raises."""
    try:
        paths = [str(path) for path in getattr(settings, setting, default)]
        timeout = float(getattr(settings, "KARNI_HEALTH_TIMEOUT", DEFAULT_TIMEOUT))
    except Exception as exc:  # noqa: BLE001 - readiness must never raise
        detail = str(exc) or type(exc).__name__
        return JsonResponse(
            {
                "status": "fail",
                "failing": ["settings"],
                "checks": {"settings": {"ok": False, "detail": detail}},
            },
            status=503,
        )

    checks: dict[str, dict[str, bool | str]] = {}
    for path in paths:
        ok, detail = _run_check(path, timeout)
        checks[_check_name(path)] = {"ok": ok, "detail": detail}

    failing = [name for name, entry in checks.items() if not entry["ok"]]
    return JsonResponse(
        {"status": "fail" if failing else "ok", "failing": failing, "checks": checks},
        status=503 if failing else 200,
    )


def _check_name(dotted_path: str) -> str:
    """Derive a check's payload key from its dotted path.

    The final path segment is used, minus a leading ``check_`` prefix:
    ``"karni.health.checks.check_database"`` becomes ``"database"``.
    """
    return dotted_path.rsplit(".", 1)[-1].removeprefix("check_")


def _run_check(dotted_path: str, timeout: float = DEFAULT_TIMEOUT) -> tuple[bool, str]:
    """Import and run one check, converting any exception or a stall into a failure.

    The check runs in a daemon thread that is waited for ``timeout`` seconds, so
    a database or cache that accepts the connection and then stalls cannot hold
    the probe. Returns a normalised ``(ok, detail)`` pair; an exception's text
    (or its class name, when the text is empty) becomes the failure detail.
    """
    outcome: list[tuple[bool, str]] = []

    def run() -> None:
        try:
            check = import_string(dotted_path)
            ok, detail = check()
            outcome.append((bool(ok), str(detail)))
        except Exception as exc:  # noqa: BLE001 - readiness must never raise
            outcome.append((False, str(exc) or type(exc).__name__))
        finally:
            connections.close_all()

    worker = threading.Thread(target=run, name="karni-health-check", daemon=True)
    worker.start()
    worker.join(timeout)
    if not outcome:
        return False, f"no answer within {timeout:g}s"
    return outcome[0]
