"""Development-only capture for debugging with an agent: requests, failures and a trace.

With ``DEBUG`` on (and ``KARNI_DEBUG_CAPTURE`` not ``False``) Karni writes,
under the project root's ``.karni/`` directory:

* ``requests/<request_id>.json`` — every request: method, path, query,
  headers, body, the resolved view, the user, status, duration, error code
  (:mod:`karni.debug.middleware`);
* ``failures/<id>.json`` — every unhandled exception: the request, the view,
  viewset and serializer, the user with roles and grants, the SQL with
  duplicates grouped, the traceback with locals of Karni and project frames,
  the relevant settings (:mod:`karni.debug.failure`);
* ``trace/<YYYY-MM-DD>.jsonl`` — one event per line, each with its request id:
  request start/end, task enqueued/started/retried/succeeded/failed, email
  sent, webhook sent/received, audit batch written (:func:`trace_event`).

``karni trace``, ``karni replay`` and ``karni explain --failure`` read them.
Every value passes the audit log's redaction rules first
(:mod:`karni.debug.redact`). With ``DEBUG`` off nothing here runs: the
middleware leaves the chain at startup and :func:`trace_event` returns at once.

Override / escape hatches: ``KARNI_DEBUG_CAPTURE = False`` turns capture off;
``KARNI_DEBUG_CAPTURE_KEEP`` (200) bounds the request and failure files,
``KARNI_DEBUG_TRACE_DAYS`` (7) the trace files; subclass
:class:`karni.debug.middleware.CaptureMiddleware` (``should_capture``) to
choose which requests are recorded.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

__all__ = ["capture_enabled", "trace_event"]

logger = logging.getLogger("karni.debug")

TRACE_VERSION = 1
"""Version of the trace event format (``"v"`` on every line)."""


def capture_enabled() -> bool:
    """True only with ``DEBUG`` on and ``KARNI_DEBUG_CAPTURE`` not ``False``."""
    return bool(getattr(settings, "DEBUG", False)) and bool(
        getattr(settings, "KARNI_DEBUG_CAPTURE", True)
    )


def trace_event(
    event: str, *, request_id: str | None = None, refs: list[str] | None = None, **fields: Any
) -> None:
    """Append one event to today's ``.karni/trace/<date>.jsonl`` (development only).

    ``event`` is a dotted name (``"webhook.sent"``); ``fields`` are JSON values
    (they pass the same redaction as everything else under ``.karni/``).
    ``request_id`` defaults to the current one (:func:`karni.tracing.get_request_id`);
    an event with no id is dropped, since nothing could find it. ``refs`` names
    the rows the event is about (``["karni_payments.Payment:<pk>"]``):
    ``karni trace`` links two requests whose events share a ref — a checkout and
    the webhook that settled it.

    Never raises: a capture problem is logged on ``karni.debug`` and the
    request goes on.
    """
    if not capture_enabled():
        return
    try:
        from karni.debug import store
        from karni.tracing import get_request_id

        rid = request_id or get_request_id()
        if not rid:
            return
        store.append_event(event, rid, refs=refs, fields=fields)
    except Exception:  # noqa: BLE001 - capture must never break the work it watches
        logger.warning("karni.debug: could not write the %s trace event", event, exc_info=True)
