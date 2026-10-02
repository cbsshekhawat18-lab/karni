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

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.utils.module_loading import import_string

from karni.health.checks import DEFAULT_HEALTH_CHECKS


def liveness(request: HttpRequest) -> JsonResponse:
    """Liveness probe: return ``200 {"status": "ok"}`` without touching I/O.

    Answers "is the process up?" only; dependency health belongs to
    :func:`readiness`.  Override by routing your own view in the project's
    URLconf instead of including ``karni.health.urls``.
    """
    return JsonResponse({"status": "ok"})


def readiness(request: HttpRequest) -> JsonResponse:
    """Readiness probe: run every check in ``KARNI_HEALTH_CHECKS``.

    Each entry is a dotted path (resolved with
    ``django.utils.module_loading.import_string``) to a zero-argument
    callable returning ``(ok, detail)``.  The response is::

        {"status": "ok" | "fail",
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
    try:
        paths = [
            str(path) for path in getattr(settings, "KARNI_HEALTH_CHECKS", DEFAULT_HEALTH_CHECKS)
        ]
    except Exception as exc:  # noqa: BLE001 - readiness must never raise
        detail = str(exc) or type(exc).__name__
        return JsonResponse(
            {"status": "fail", "checks": {"settings": {"ok": False, "detail": detail}}},
            status=503,
        )

    checks: dict[str, dict[str, bool | str]] = {}
    for path in paths:
        ok, detail = _run_check(path)
        checks[_check_name(path)] = {"ok": ok, "detail": detail}

    all_ok = all(entry["ok"] for entry in checks.values())
    return JsonResponse(
        {"status": "ok" if all_ok else "fail", "checks": checks},
        status=200 if all_ok else 503,
    )


def _check_name(dotted_path: str) -> str:
    """Derive a check's payload key from its dotted path.

    The final path segment is used, minus a leading ``check_`` prefix:
    ``"karni.health.checks.check_database"`` becomes ``"database"``.
    """
    return dotted_path.rsplit(".", 1)[-1].removeprefix("check_")


def _run_check(dotted_path: str) -> tuple[bool, str]:
    """Import and run one check, converting any exception into a failure.

    Returns a normalised ``(ok, detail)`` pair; an exception's text (or its
    class name, when the text is empty) becomes the failure detail.
    """
    try:
        check = import_string(dotted_path)
        ok, detail = check()
    except Exception as exc:  # noqa: BLE001 - readiness must never raise
        return False, str(exc) or type(exc).__name__
    return bool(ok), str(detail)
