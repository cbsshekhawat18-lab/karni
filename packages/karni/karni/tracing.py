"""One request id across the whole system.

Every HTTP request gets an id (:class:`RequestIdMiddleware`); everything the
request causes carries it:

* **logs** — bound into structlog's context, and written into
  ``X-Request-ID`` so django-structlog's ``RequestMiddleware`` logs the same id;
* **the response** — ``X-Request-ID: <id>``, so a person or a browser test can
  hand it to ``karni trace``;
* **Celery tasks** enqueued while it runs, and their retries — a
  ``karni_request_id`` message header written on ``before_task_publish`` and
  restored on ``task_prerun`` (a retry is published from inside the running
  task, so it inherits the same id); a task started with no id (beat, a
  shell) gets a fresh one, so its own work still correlates;
* **email** — ``X-Karni-Request-ID`` on every ``EmailMessage.send()``;
* **outgoing HTTP** — :func:`outgoing_headers` for the call you make;
* **change history** — ``ChangeLog.request_id`` and ``ChangeBatch.request_id``.

The id is the client's ``X-Request-ID`` only when it can be trusted: with
``DEBUG`` on, or when ``KARNI_REQUEST_ID_TRUST_HEADER`` says the proxy in front
overwrites it (and ``NUM_PROXIES`` says there is a proxy). Otherwise it is a
fresh UUID and the client's value is replaced, so a client cannot write ids
into production logs. Ids are ``[A-Za-z0-9_-]{1,128}`` (they name files under
``.karni/`` in development); anything else is replaced too.

Override / escape hatches: remove ``karni.tracing.RequestIdMiddleware`` from
``MIDDLEWARE``; ``KARNI_REQUEST_ID_EMAILS = False`` leaves ``EmailMessage``
alone; :func:`bound_request_id` sets the id for a block (a management command,
a test).
"""

from __future__ import annotations

import functools
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, Final

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.conf import settings
from django.http import HttpRequest, HttpResponseBase

__all__ = [
    "CELERY_HEADER",
    "EMAIL_HEADER",
    "REQUEST_ID_HEADER",
    "RequestIdMiddleware",
    "bound_request_id",
    "connect",
    "get_request_id",
    "is_valid_request_id",
    "new_request_id",
    "outgoing_headers",
]

logger = logging.getLogger("karni.tracing")

#: The HTTP header carrying the id: read (when trusted) and set on every response.
REQUEST_ID_HEADER: Final = "X-Request-ID"
#: The header stamped on outgoing email.
EMAIL_HEADER: Final = "X-Karni-Request-ID"
#: The Celery message header carrying the id to the worker.
CELERY_HEADER: Final = "karni_request_id"

_META_KEY: Final = "HTTP_X_REQUEST_ID"
_VALID: Final = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_UID: Final = "karni.tracing."

_request_id: ContextVar[str | None] = ContextVar("karni_request_id", default=None)


def get_request_id() -> str | None:
    """The id of the unit of work running now (a request, a task), or ``None``."""
    return _request_id.get()


def new_request_id() -> str:
    """A fresh id (a UUID4 string, the format django-structlog generates)."""
    return str(uuid.uuid4())


def is_valid_request_id(value: Any) -> bool:
    """True for a string of 1–128 letters, digits, ``_`` and ``-`` (safe as a file name)."""
    return isinstance(value, str) and _VALID.match(value) is not None


def _bind(value: str | None) -> tuple[Token[str | None], Mapping[str, Any]]:
    import structlog

    token = _request_id.set(value)
    bound = structlog.contextvars.bind_contextvars(request_id=value) if value else {}
    return token, bound


def _unbind(token: Token[str | None], bound: Mapping[str, Any]) -> None:
    import structlog

    if bound:
        structlog.contextvars.reset_contextvars(**bound)
    _request_id.reset(token)


@contextmanager
def bound_request_id(value: str | None = None) -> Iterator[str]:
    """Run a block under ``value`` (a fresh id when ``None``); yields the id.

    For work outside a request that should still correlate — a management
    command, a script, a test: ``with bound_request_id() as rid: ...``.
    """
    rid = value if value is not None and is_valid_request_id(value) else new_request_id()
    token, bound = _bind(rid)
    try:
        yield rid
    finally:
        _unbind(token, bound)


def outgoing_headers() -> dict[str, str]:
    """``{"X-Request-ID": <id>}`` for an outgoing HTTP call (a webhook), or ``{}``.

    ``requests.post(url, json=payload, headers={**outgoing_headers(), ...})``
    lets the receiver log the same id. Pair it with
    ``karni.debug.trace_event("webhook.sent", url=url, status=...)`` to see the
    call in ``karni trace``.
    """
    rid = get_request_id()
    return {REQUEST_ID_HEADER: rid} if rid else {}


def _num_proxies() -> Any:
    rest = getattr(settings, "REST_FRAMEWORK", None) or {}
    return rest.get("NUM_PROXIES") if isinstance(rest, Mapping) else None


def trusts_incoming_id() -> bool:
    """Whether a client-supplied ``X-Request-ID`` may become the request's id.

    In development (``DEBUG``) always. Otherwise only when
    ``KARNI_REQUEST_ID_TRUST_HEADER`` is on — the proxy in front overwrites the
    header on every request — and ``NUM_PROXIES`` is not 0 (the same trust
    model as ``X-Forwarded-For``: with no proxy, every header is the client's).
    """
    if getattr(settings, "DEBUG", False):
        return True
    return bool(getattr(settings, "KARNI_REQUEST_ID_TRUST_HEADER", False)) and _num_proxies() != 0


def request_id_for(request: HttpRequest) -> str:
    """The id ``request`` runs under: the trusted, valid incoming one, else a new one.

    Also writes it into ``request.META`` (so django-structlog and anything
    reading ``request.headers`` see the same value) and onto
    ``request.request_id``.
    """
    existing = getattr(request, "request_id", None)
    if is_valid_request_id(existing):
        return str(existing)
    incoming = request.META.get(_META_KEY)
    rid = incoming if is_valid_request_id(incoming) and trusts_incoming_id() else new_request_id()
    # What the client actually sent (the capture records headers as received).
    request._karni_incoming_request_id = incoming  # type: ignore[attr-defined]
    request.META[_META_KEY] = rid
    # request.headers is a cached view of META: drop it so it is rebuilt with the id.
    request.__dict__.pop("headers", None)
    request.request_id = rid  # type: ignore[attr-defined]
    return rid


class RequestIdMiddleware:
    """Give every request one id: logs, response header, tasks, email and history carry it.

    Put it first in ``MIDDLEWARE`` (Karni's defaults do), before
    django-structlog's ``RequestMiddleware``, so every log line of the request
    has the id; ``karni.W920`` warns when it comes after. See the module
    docstring for the trust rule and the escape hatches.
    """

    sync_capable = True
    async_capable = True

    def __init__(
        self,
        get_response: Callable[[HttpRequest], HttpResponseBase]
        | Callable[[HttpRequest], Awaitable[HttpResponseBase]],
    ) -> None:
        self.get_response = get_response
        if iscoroutinefunction(self.get_response):
            markcoroutinefunction(self)

    def __call__(self, request: HttpRequest) -> Any:
        if iscoroutinefunction(self):
            return self.__acall__(request)
        token, bound = _bind(request_id_for(request))
        try:
            response = self.get_response(request)
        finally:
            _unbind(token, bound)
        return self._stamp(request, response)  # type: ignore[arg-type]

    async def __acall__(self, request: HttpRequest) -> HttpResponseBase:
        token, bound = _bind(request_id_for(request))
        try:
            response = await self.get_response(request)  # type: ignore[misc]
        finally:
            _unbind(token, bound)
        return self._stamp(request, response)

    @staticmethod
    def _stamp(request: HttpRequest, response: HttpResponseBase) -> HttpResponseBase:
        if REQUEST_ID_HEADER not in response:
            response[REQUEST_ID_HEADER] = request.request_id  # type: ignore[attr-defined]
        return response


# --- Celery ------------------------------------------------------------------

#: task id -> stack of (contextvar token, structlog tokens, start time); a
#: stack because an eager retry runs the same task id nested.
_RUNNING: dict[str, list[tuple[Token[str | None], Mapping[str, Any], float]]] = {}


def _header_id(request: Any) -> str | None:
    """The id a task message carried (a top-level header, or inside ``headers``)."""
    if request is None:
        return None
    found = getattr(request, CELERY_HEADER, None)
    if not is_valid_request_id(found):
        headers = getattr(request, "headers", None)
        found = headers.get(CELERY_HEADER) if isinstance(headers, Mapping) else None
    return found if is_valid_request_id(found) else None


def _task_name(task: Any) -> str:
    return str(getattr(task, "name", None) or task or "")


def _trace(event: str, **fields: Any) -> None:
    from karni.debug import trace_event

    trace_event(event, **fields)


def _before_task_publish(sender: Any = None, headers: Any = None, **_kwargs: Any) -> None:
    rid = get_request_id()
    if rid and isinstance(headers, dict) and not headers.get(CELERY_HEADER):
        headers[CELERY_HEADER] = rid


def _after_task_publish(
    sender: Any = None, headers: Any = None, routing_key: Any = None, **_kwargs: Any
) -> None:
    headers = headers if isinstance(headers, Mapping) else {}
    rid = headers.get(CELERY_HEADER) or get_request_id()
    _trace(
        "task.enqueued",
        request_id=rid,
        task=str(headers.get("task") or sender or ""),
        task_id=headers.get("id"),
        retries=headers.get("retries") or 0,
        eta=headers.get("eta"),
        queue=routing_key or None,
    )


def _task_prerun(sender: Any = None, task_id: Any = None, task: Any = None, **_kw: Any) -> None:
    request = getattr(task, "request", None)
    # An eager task runs inside its caller and keeps the caller's id; a task
    # with no id at all (beat, a shell) starts its own.
    rid = _header_id(request) or get_request_id() or new_request_id()
    token, bound = _bind(rid)
    _RUNNING.setdefault(str(task_id), []).append((token, bound, time.perf_counter()))
    _trace(
        "task.started",
        task=_task_name(task),
        task_id=task_id,
        retries=getattr(request, "retries", 0) or 0,
        eager=bool(getattr(request, "is_eager", False)),
    )


def _elapsed_ms(task_id: Any) -> float | None:
    stack = _RUNNING.get(str(task_id))
    if not stack:
        return None
    return round((time.perf_counter() - stack[-1][2]) * 1000, 3)


def _task_postrun(sender: Any = None, task_id: Any = None, **_kwargs: Any) -> None:
    stack = _RUNNING.get(str(task_id))
    if not stack:
        return
    token, bound, _started = stack.pop()
    if not stack:
        _RUNNING.pop(str(task_id), None)
    try:
        _unbind(token, bound)
    except ValueError:  # reset from another context (a pool quirk): just clear
        _request_id.set(None)


def _task_success(sender: Any = None, **_kwargs: Any) -> None:
    task_id = getattr(getattr(sender, "request", None), "id", None)
    _trace(
        "task.succeeded",
        task=_task_name(sender),
        task_id=task_id,
        duration_ms=_elapsed_ms(task_id),
    )


def _task_retry(sender: Any = None, request: Any = None, reason: Any = None, **_kw: Any) -> None:
    _trace(
        "task.retried",
        task=_task_name(sender),
        task_id=getattr(request, "id", None),
        retries=getattr(request, "retries", 0) or 0,
        reason=str(reason)[:500] if reason is not None else None,
    )


def _task_failure(
    sender: Any = None,
    task_id: Any = None,
    exception: BaseException | None = None,
    traceback: Any = None,
    **_kwargs: Any,
) -> None:
    from karni.debug import capture_enabled

    failure_id = None
    if capture_enabled() and exception is not None:
        from karni.debug.failure import capture_task_failure

        failure_id = capture_task_failure(sender, task_id, exception, traceback)
    _trace(
        "task.failed",
        task=_task_name(sender),
        task_id=task_id,
        duration_ms=_elapsed_ms(task_id),
        exception=type(exception).__name__ if exception is not None else None,
        message=str(exception)[:500] if exception is not None else None,
        failure_id=failure_id,
    )


def connect_celery() -> None:
    """Connect the Celery signal receivers (idempotent; ``KarniAppConfig.ready`` calls it)."""
    from celery import signals

    pairs: tuple[tuple[Any, Callable[..., None]], ...] = (
        (signals.before_task_publish, _before_task_publish),
        (signals.after_task_publish, _after_task_publish),
        (signals.task_prerun, _task_prerun),
        (signals.task_postrun, _task_postrun),
        (signals.task_success, _task_success),
        (signals.task_retry, _task_retry),
        (signals.task_failure, _task_failure),
    )
    for signal, receiver in pairs:
        signal.connect(receiver, weak=False, dispatch_uid=_UID + receiver.__name__)


# --- Email -------------------------------------------------------------------


def install_email_header() -> None:
    """Wrap ``EmailMessage.send`` to stamp ``X-Karni-Request-ID`` and trace the send.

    Every Django mail path that sends a message object goes through it
    (``send_mail``, ``mail_admins``, ``EmailMessage.send()``, Karni's account
    emails); ``connection.send_messages([...])`` called directly is not seen.
    Idempotent. Escape hatch: ``KARNI_REQUEST_ID_EMAILS = False``.
    """
    from django.core.mail import EmailMessage

    original = EmailMessage.send
    if getattr(original, "_karni_traced", False):
        return

    @functools.wraps(original)
    def send(self: EmailMessage, fail_silently: bool = False) -> int:
        rid = get_request_id()
        if rid and isinstance(self.extra_headers, dict):
            self.extra_headers.setdefault(EMAIL_HEADER, rid)
        sent = original(self, fail_silently)
        _trace(
            "email.sent",
            to=[str(address) for address in self.to],
            cc=len(self.cc),
            bcc=len(self.bcc),
            subject=str(self.subject)[:200],
            sent=sent,
        )
        return sent

    send._karni_traced = True  # type: ignore[attr-defined]
    EmailMessage.send = send  # type: ignore[method-assign]


def connect() -> None:
    """Everything this module wires at startup: Celery receivers, the email header."""
    connect_celery()
    if getattr(settings, "KARNI_REQUEST_ID_EMAILS", True):
        install_email_header()
