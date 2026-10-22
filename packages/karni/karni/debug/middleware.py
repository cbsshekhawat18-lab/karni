"""``CaptureMiddleware``: one request record per request, a failure snapshot per crash (DEBUG only).

The request record (``.karni/requests/<request_id>.json``) is a contract other
tools read (``karni why``, ``karni replay``); version 1 has exactly these keys::

    {"version": 1, "request_id": str, "at": ISO-8601 str, "method": str, "path": str,
     "query": {str: [str]}, "headers": {str: str}, "body": JSON value | null,
     "content_type": str | null,
     "user": {"id": str, "email": str | null, "username": str | null,
              "is_staff": bool, "is_superuser": bool} | null,
     "view": str, "resource": str | null, "action": str | null, "view_kwargs": {str: str},
     "status": int, "duration_ms": float, "error_code": str | null, "failure_id": str | null}

``view`` is the dotted path of the view (the viewset class for a DRF
viewset; ``""`` when no URL matched), ``resource`` the router basename and
``action`` the DRF action. ``headers``, ``query`` and ``body`` are redacted
(:mod:`karni.debug.redact`). ``body`` is the parsed JSON, a form as
``{field: value | [values]}`` (an upload as ``"<file name.pdf, 1234 bytes>"``),
a short note for a body that is not captured (another content type, over
64 KiB), or ``null``. ``error_code`` is the Karni code the response carries
(``E801``), else DRF's code for an error response (``permission_denied``,
``not_found``, ``invalid``...), else ``null``. ``failure_id`` names the
failure snapshot when the request raised.

Override / escape hatch: ``KARNI_DEBUG_CAPTURE = False``; subclass and
override :meth:`CaptureMiddleware.should_capture` (static and media files and
CORS preflights are skipped by default) or ``max_body_bytes``.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Final

from django.conf import settings
from django.core.exceptions import MiddlewareNotUsed
from django.http import HttpRequest, HttpResponseBase

from karni.debug import capture_enabled, trace_event

__all__ = ["RECORD_VERSION", "CaptureMiddleware", "current_capture"]

logger = logging.getLogger("karni.debug")

#: Version of the request record contract.
RECORD_VERSION: Final = 1

_KARNI_CODE: Final = re.compile(r"^(?:[EWC]\d{3}|[A-Z]{2,5}\d{3})$")
_CODE_PREFIX: Final = re.compile(r"^((?:[EWC]\d{3}|[A-Z]{2,5}\d{3})): ")
_JSON_TYPES: Final = ("application/json", "+json")
_FORM_TYPES: Final = ("application/x-www-form-urlencoded", "multipart/form-data")
_UNPARSED: Final = object()


@dataclass
class Capture:
    """What the middleware knows about the request it is recording."""

    request: HttpRequest
    request_id: str
    at: str
    started: float
    redactor: Any
    raw_body: bytes | None = None
    body_note: str | None = None
    view_func: Callable[..., Any] | None = None
    view_kwargs: dict[str, Any] = field(default_factory=dict)
    recorder: Any = None
    failure_id: str | None = None


_current: ContextVar[Capture | None] = ContextVar("karni_debug_capture", default=None)


def current_capture() -> Capture | None:
    """The request being recorded in this context, or ``None``."""
    return _current.get()


def _content_type(request: HttpRequest) -> str | None:
    value = request.META.get("CONTENT_TYPE") or ""
    return value or None


def _media_type(request: HttpRequest) -> str:
    return (_content_type(request) or "").split(";")[0].strip().lower()


def received_headers(request: HttpRequest) -> dict[str, str]:
    """The request's headers as the client sent them (not the ``X-Request-ID`` Karni set)."""
    headers = dict(request.headers)
    marker = "_karni_incoming_request_id"
    if hasattr(request, marker) and not getattr(request, marker):
        headers = {name: value for name, value in headers.items() if name.lower() != "x-request-id"}
    return headers


def dotted(obj: Any) -> str:
    """``module.QualName`` of a class or function."""
    module = getattr(obj, "__module__", None) or ""
    name = getattr(obj, "__qualname__", None) or getattr(obj, "__name__", None) or repr(obj)
    return f"{module}.{name}" if module else str(name)


def view_identity(view_func: Callable[..., Any] | None, method: str) -> dict[str, Any]:
    """``view`` (dotted), ``resource`` (router basename) and ``action`` of a resolved view."""
    if view_func is None:
        return {"view": "", "resource": None, "action": None, "viewset": None}
    cls = getattr(view_func, "cls", None) or getattr(view_func, "view_class", None)
    initkwargs = getattr(view_func, "initkwargs", None) or {}
    actions = getattr(view_func, "actions", None) or {}
    action = actions.get(method.lower()) if isinstance(actions, Mapping) else None
    if action is None and isinstance(actions, Mapping) and method.upper() == "HEAD":
        action = actions.get("get")
    basename = initkwargs.get("basename") if isinstance(initkwargs, Mapping) else None
    return {
        "view": dotted(cls if cls is not None else view_func),
        "resource": str(basename) if basename else None,
        "action": str(action) if action else None,
        "viewset": cls,
    }


def user_record(user: Any) -> dict[str, Any] | None:
    """The record's ``user``: id, email, username, staff, superuser (``None``: anonymous)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    username = getattr(user, "username", None)
    email = getattr(user, "email", None)
    return {
        "id": str(user.pk),
        "email": str(email) if email else None,
        "username": username if isinstance(username, str) and username else None,
        "is_staff": bool(getattr(user, "is_staff", False)),
        "is_superuser": bool(getattr(user, "is_superuser", False)),
    }


def _first_code(data: Any, depth: int = 0) -> tuple[str | None, str | None]:
    """(Karni code, DRF code) of the first error detail in a DRF response's data."""
    if depth > 6:
        return None, None
    code = getattr(data, "code", None)
    if isinstance(code, str):
        if _KARNI_CODE.match(code):
            return code, None
        prefixed = _CODE_PREFIX.match(str(data))
        return (prefixed.group(1) if prefixed else None), code
    values: list[Any] = []
    if isinstance(data, Mapping):
        values = list(data.values())
    elif isinstance(data, list | tuple):
        values = list(data)
    drf: str | None = None
    for item in values:
        karni, found = _first_code(item, depth + 1)
        if karni:
            return karni, None
        drf = drf or found
    return None, drf


def error_code(response: HttpResponseBase) -> str | None:
    """The record's ``error_code`` for ``response`` (see the module docstring)."""
    if response.status_code < 400:
        return None
    data = getattr(response, "data", None)
    karni, drf = _first_code(data) if data is not None else (None, None)
    return karni or drf


class CaptureMiddleware:
    """Record every request under ``.karni/`` in development (see the module docstring).

    Not in the chain at all with ``DEBUG`` off: ``__init__`` raises
    ``MiddlewareNotUsed`` and Django drops it when it builds the handler.
    Sync only; Django adapts it for async stacks.
    """

    sync_capable = True
    async_capable = False

    #: Bodies larger than this are noted, not captured.
    max_body_bytes: int = 64 * 1024

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponseBase]) -> None:
        if not capture_enabled():
            raise MiddlewareNotUsed
        self.get_response = get_response

    def should_capture(self, request: HttpRequest) -> bool:
        """Every request except CORS preflights and static or media files."""
        if request.method == "OPTIONS":
            return False
        path = request.path_info or request.path
        for prefix in (getattr(settings, "STATIC_URL", None), getattr(settings, "MEDIA_URL", None)):
            if prefix and str(prefix).startswith("/") and path.startswith(str(prefix)):
                return False
        return path != "/favicon.ico"

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        if not capture_enabled() or not self.should_capture(request):
            return self.get_response(request)
        from karni.debug.redact import Redactor, activate, deactivate
        from karni.debug.store import now_iso
        from karni.performance import record_queries
        from karni.tracing import bound_request_id, get_request_id, request_id_for

        rid = get_request_id() or request_id_for(request)
        capture = Capture(
            request=request,
            request_id=rid,
            at=now_iso(),
            started=time.perf_counter(),
            redactor=Redactor(),
        )
        self._read_body(capture)
        capture.redactor.collect_headers(request.headers)
        capture.redactor.collect(dict(request.GET.lists()))
        token = _current.set(capture)
        redactor_token = activate(capture.redactor)
        try:
            with bound_request_id(rid):
                self._start(capture)
                with record_queries() as recorder:
                    capture.recorder = recorder
                    response = self.get_response(request)
                self._finish(capture, response)
        finally:
            deactivate(redactor_token)
            _current.reset(token)
        return response

    def process_view(
        self,
        request: HttpRequest,
        view_func: Callable[..., Any],
        view_args: tuple[Any, ...],
        view_kwargs: dict[str, Any],
    ) -> None:
        capture = _current.get()
        if capture is not None and capture.request is request:
            capture.view_func = view_func
            capture.view_kwargs = dict(view_kwargs)

    # --- body --------------------------------------------------------------------

    def _read_body(self, capture: Capture) -> None:
        """Read a JSON or urlencoded body now (Django caches it for the view)."""
        request = capture.request
        media = _media_type(request)
        try:
            length = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        if length <= 0 or media.startswith("multipart/"):
            return  # multipart is read from the parsed form after the view
        if length > self.max_body_bytes:
            capture.body_note = f"<{length} bytes, not captured (over {self.max_body_bytes})>"
            return
        if not (media.endswith(_JSON_TYPES) or media == _FORM_TYPES[0]):
            capture.body_note = f"<{length} bytes of {media or 'unknown type'}, not captured>"
            return
        try:
            capture.raw_body = request.body
        except Exception:  # noqa: BLE001 - a body Django refuses is the view's problem
            capture.body_note = "<body not readable>"
            return
        parsed = parse_body(capture)
        if parsed is not _UNPARSED:
            capture.redactor.collect(parsed)

    # --- record ------------------------------------------------------------------

    def _start(self, capture: Capture) -> None:
        request = capture.request
        replay_of = request.META.get("HTTP_X_KARNI_REPLAY_OF")
        trace_event(
            "request.start",
            request_id=capture.request_id,
            method=request.method,
            path=request.path,
            replay_of=replay_of if isinstance(replay_of, str) else None,
        )

    def _finish(self, capture: Capture, response: HttpResponseBase) -> None:
        duration = round((time.perf_counter() - capture.started) * 1000, 3)
        try:
            record = self.build_record(capture, response, duration)
            from karni.debug.store import write_request

            write_request(record)
        except Exception:  # noqa: BLE001 - capture must never break the request
            logger.warning("karni.debug: could not write the request record", exc_info=True)
            record = None
        trace_event(
            "request.end",
            request_id=capture.request_id,
            method=capture.request.method,
            path=capture.request.path,
            status=response.status_code,
            duration_ms=duration,
            view=record["view"] if record else None,
            user=(record["user"] or {}).get("id") if record else None,
            error_code=record["error_code"] if record else None,
            failure_id=capture.failure_id,
        )

    def build_record(
        self, capture: Capture, response: HttpResponseBase, duration_ms: float
    ) -> dict[str, Any]:
        """The version-1 request record (the contract in the module docstring)."""
        request = capture.request
        redactor = capture.redactor
        identity = view_identity(capture.view_func, request.method or "GET")
        return {
            "version": RECORD_VERSION,
            "request_id": capture.request_id,
            "at": capture.at,
            "method": request.method or "",
            "path": request.path,
            "query": redactor.query(request.GET.lists()),
            "headers": redactor.headers(received_headers(request)),
            "body": render_body(capture),
            "content_type": _content_type(request),
            "user": redactor.value(user_record(getattr(request, "user", None))),
            "view": identity["view"],
            "resource": identity["resource"],
            "action": identity["action"],
            "view_kwargs": {
                str(name): redactor.scrub(str(value)) for name, value in capture.view_kwargs.items()
            },
            "status": int(response.status_code),
            "duration_ms": duration_ms,
            "error_code": error_code(response),
            "failure_id": capture.failure_id,
        }


def _multipart(request: HttpRequest) -> Any:
    post = request.__dict__.get("_post")
    files = request.__dict__.get("_files")
    if post is None:
        return _UNPARSED
    found: dict[str, Any] = {
        name: values[0] if len(values) == 1 else values for name, values in post.lists()
    }
    for name, uploads in files.lists() if files is not None else []:
        notes = [f"<file {upload.name}, {upload.size} bytes>" for upload in uploads]
        found[name] = notes[0] if len(notes) == 1 else notes
    return found


def parse_body(capture: Capture) -> Any:
    """The request body as data: parsed JSON, a form dict, or ``_UNPARSED``."""
    request = capture.request
    media = _media_type(request)
    if media.startswith("multipart/"):
        return _multipart(request)
    raw = capture.raw_body
    if raw is None:
        return _UNPARSED
    if media == _FORM_TYPES[0]:
        from django.http import QueryDict

        form = QueryDict(raw, encoding=request.encoding or settings.DEFAULT_CHARSET)
        return {name: values[0] if len(values) == 1 else values for name, values in form.lists()}
    try:
        return json.loads(raw.decode(request.encoding or "utf-8"))
    except ValueError:
        return _UNPARSED


def render_body(capture: Capture) -> Any:
    """The record's ``body``: redacted data, a note, or ``None``."""
    if capture.body_note:
        return capture.body_note
    parsed = parse_body(capture)
    if parsed is _UNPARSED:
        if capture.raw_body:
            return f"<{len(capture.raw_body)} bytes, not valid JSON>"
        return None
    # A multipart form is parsed only by the view: learn its secrets now.
    capture.redactor.collect(parsed)
    return capture.redactor.value(parsed)


def on_request_exception(sender: Any = None, request: Any = None, **_kwargs: Any) -> None:
    """``got_request_exception`` receiver: snapshot the failure of the request being recorded."""
    capture = _current.get()
    if capture is None or capture.failure_id or not capture_enabled():
        return
    import sys

    exc = sys.exc_info()[1]
    if exc is None:
        return
    from karni.debug.failure import capture_request_failure

    capture.failure_id = capture_request_failure(capture, exc)


def connect() -> None:
    """Connect the exception receiver (idempotent; ``KarniAppConfig.ready`` calls it)."""
    from django.core.signals import got_request_exception

    got_request_exception.connect(
        on_request_exception, weak=False, dispatch_uid="karni.debug.on_request_exception"
    )
