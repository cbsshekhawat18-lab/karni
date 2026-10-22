"""Re-run a captured request against the current code, in-process, as its user or another.

:func:`replay` sends the captured method, path, query, body and plain headers
through Django's test client (DRF's ``APIClient``, force-authenticated as the
captured user or ``as_user``; no server needed) and compares the status with
the captured one.

**Writes are rolled back by default.** The request runs inside
``transaction.atomic()`` on every database, rolled back at the end;
``transaction.on_commit`` work (queued listeners, the payments webhook task)
is therefore discarded, mail goes to Django's in-memory backend and is listed
instead of sent, and a Celery task the view enqueues directly runs eagerly
inside the same transaction. External HTTP calls the view (or such a task)
makes are not contained. ``commit=True`` (``--commit``) keeps the writes and
uses the project's real mail backend and broker.

**Redacted values cannot be replayed.** A body or query value captured as
``"[redacted]"`` is refused until it is supplied (``sets``:
``{"password": "..."}``, ``{"query:token": "..."}``) or dropped
(``drop_redacted``) — replaying the literal ``"[redacted]"`` could, say, set a
password to it. Credentials headers are never replayed: the client is
force-authenticated instead.

Refuses with ``DEBUG`` off (``E920``).
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any, Final
from urllib.parse import urlencode

from django.conf import settings

from karni.audit import REDACTED
from karni.exceptions import KarniCommandError

__all__ = ["ReplayResult", "redacted_paths", "render", "replay", "resolve_user"]

_SKIP_HEADERS: Final = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "x-csrftoken",
        "x-csrf-token",
        "content-length",
        "content-type",
        "host",
        "x-request-id",
        "connection",
        "accept-encoding",
    }
)
_EXCERPT: Final = 300


@dataclass
class ReplayResult:
    """What a replay did: the statuses, a body excerpt, the new request id, mail."""

    request_id: str
    method: str
    path: str
    user: str
    was_status: int | None
    status: int
    excerpt: str
    committed: bool
    new_request_id: str | None = None
    failure_id: str | None = None
    emails: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def change(self) -> str:
        """``was 403, now 200`` / ``same as captured (200)``."""
        if self.was_status is None:
            return f"now {self.status}"
        if self.was_status == self.status:
            return f"same as captured ({self.status})"
        return f"was {self.was_status}, now {self.status}"

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "change": self.change}


def redacted_paths(record: Mapping[str, Any]) -> list[str]:
    """Where the record holds ``"[redacted]"``: body paths (``card.token``) and ``query:name``."""
    found: list[str] = []

    def walk(value: Any, path: str) -> None:
        if value == REDACTED:
            found.append(path)
        elif isinstance(value, Mapping):
            for key, item in value.items():
                walk(item, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}.{index}" if path else str(index))

    walk(record.get("body"), "")
    for name, values in (record.get("query") or {}).items():
        if REDACTED in values:
            found.append(f"query:{name}")
    return found


def _parse_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _set_path(body: Any, path: str, value: Any) -> Any:
    if not isinstance(body, dict | list):
        body = {}
    target: Any = body
    parts = path.split(".")
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        if isinstance(target, list) and part.isdigit() and int(part) < len(target):
            if last:
                target[int(part)] = value
            else:
                target = target[int(part)]
            continue
        if not isinstance(target, dict):
            raise KarniCommandError(
                f"--set {path}=...: {'.'.join(parts[:index]) or 'the body'} is not an object.",
                code="E923",
            )
        if last:
            target[part] = value
        else:
            target = target.setdefault(part, {})
    return body


def _drop_path(body: Any, path: str) -> None:
    parts = path.split(".")
    target: Any = body
    for part in parts[:-1]:
        if isinstance(target, list) and part.isdigit():
            target = target[int(part)]
        elif isinstance(target, dict):
            target = target.get(part)
        else:
            return
    if isinstance(target, dict):
        target.pop(parts[-1], None)
    elif isinstance(target, list) and parts[-1].isdigit() and int(parts[-1]) < len(target):
        target.pop(int(parts[-1]))


def resolve_user(spec: str) -> Any:
    """The user named by ``spec``: a primary key, an email, or a username (case-insensitive)."""
    from django.contrib.auth import get_user_model
    from django.core.exceptions import FieldDoesNotExist, ValidationError

    model = get_user_model()
    manager = model._default_manager
    try:
        value = model._meta.pk.to_python(spec)
        found = manager.filter(pk=value).first()
        if found is not None:
            return found
    except (ValidationError, ValueError, TypeError):
        pass
    for name in dict.fromkeys(("email", model.USERNAME_FIELD, "username")):
        try:
            model._meta.get_field(name)
        except FieldDoesNotExist:
            continue
        found = manager.filter(**{f"{name}__iexact": spec}).first()
        if found is not None:
            return found
    raise KarniCommandError(
        f"No user {spec!r}: --as takes a primary key, an email or a username of an existing "
        "user (`karni shell` to look one up), or use --anonymous.",
        code="E924",
    )


def _captured_user(record: Mapping[str, Any]) -> Any:
    captured = record.get("user")
    if not captured:
        return None
    from django.contrib.auth import get_user_model

    user = get_user_model()._default_manager.filter(pk=captured.get("id")).first()
    if user is None:
        raise KarniCommandError(
            f"The captured user (id {captured.get('id')}, {captured.get('email')}) no longer "
            "exists. Replay as someone else with --as <email|username|pk>, or --anonymous.",
            code="E924",
        )
    return user


def _label(user: Any) -> str:
    if user is None:
        return "anonymous"
    return str(getattr(user, "email", None) or getattr(user, "username", None) or f"user {user.pk}")


@contextmanager
def _rolled_back() -> Iterator[list[Any]]:
    """Atomic blocks on every database, rolled back; mail to memory; Celery eager."""
    from celery import current_app
    from django.core import mail
    from django.db import connections, transaction
    from django.test.utils import override_settings

    had_outbox = hasattr(mail, "outbox")
    previous_outbox = getattr(mail, "outbox", None)
    mail.outbox = []
    conf = current_app.conf
    previous_eager = conf.task_always_eager
    try:
        with ExitStack() as stack:
            stack.enter_context(
                override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
            )
            # Both spellings: namespaced lookups consult CELERY_* first (karni.celery).
            conf.update(task_always_eager=True, CELERY_TASK_ALWAYS_EAGER=True)
            aliases = list(connections)
            for alias in aliases:
                stack.enter_context(transaction.atomic(using=alias))
            try:
                yield mail.outbox
            finally:
                for alias in aliases:
                    transaction.set_rollback(True, using=alias)
    finally:
        conf.update(task_always_eager=previous_eager, CELERY_TASK_ALWAYS_EAGER=previous_eager)
        if had_outbox:
            mail.outbox = previous_outbox
        else:
            del mail.outbox


def _request_kwargs(
    record: Mapping[str, Any], body: Any, query: dict[str, list[str]]
) -> tuple[dict[str, Any], list[str]]:
    from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart

    notes: list[str] = []
    content_type = str(record.get("content_type") or "")
    media = content_type.split(";")[0].strip().lower()
    kwargs: dict[str, Any] = {"QUERY_STRING": urlencode(query, doseq=True)}
    if isinstance(body, str) and body.startswith("<"):
        notes.append(f"the body was not captured ({body}); replayed without it")
        body = None
    if body is not None:
        if media.startswith("multipart/"):
            fields = {
                key: value
                for key, value in (body if isinstance(body, dict) else {}).items()
                if not (isinstance(value, str) and value.startswith("<file "))
            }
            if len(fields) != len(body if isinstance(body, dict) else {}):
                notes.append("uploaded files are not captured; replayed without them")
            kwargs["data"] = encode_multipart(BOUNDARY, fields)
            kwargs["content_type"] = MULTIPART_CONTENT
        elif media == "application/x-www-form-urlencoded":
            kwargs["data"] = urlencode(body if isinstance(body, dict) else {}, doseq=True)
            kwargs["content_type"] = media
        else:
            kwargs["data"] = json.dumps(body)
            kwargs["content_type"] = content_type or "application/json"
    headers = record.get("headers") or {}
    for name, value in headers.items():
        lower = str(name).lower()
        if lower in _SKIP_HEADERS or REDACTED in str(value):
            continue
        kwargs["HTTP_" + lower.upper().replace("-", "_")] = str(value)
    host = next((v for k, v in headers.items() if str(k).lower() == "host"), None)
    kwargs["HTTP_HOST"] = str(host) if host and REDACTED not in str(host) else "localhost"
    kwargs["HTTP_X_KARNI_REPLAY_OF"] = str(record.get("request_id") or "")
    return kwargs, notes


def _excerpt(response: Any) -> str:
    if getattr(response, "streaming", False):
        return "<streaming response>"
    content = bytes(getattr(response, "content", b"") or b"")
    media = str(response.get("Content-Type", "")).split(";")[0].strip().lower()
    if not content:
        return ""
    if media.endswith("json"):
        from karni.debug.redact import Redactor

        try:
            data = json.loads(content)
        except ValueError:
            data = None
        if data is not None:
            text = json.dumps(Redactor().value(data), ensure_ascii=False, separators=(",", ":"))
            return text if len(text) <= _EXCERPT else text[:_EXCERPT] + "…"
    if media.startswith("text/") or media.endswith(("xml", "javascript")):
        text = " ".join(content.decode("utf-8", "replace").split())
        return text if len(text) <= _EXCERPT else text[:_EXCERPT] + "…"
    return f"<{len(content)} bytes of {media or 'unknown type'}>"


def replay(
    record: Mapping[str, Any],
    *,
    as_user: str | None = None,
    anonymous: bool = False,
    sets: Mapping[str, str] | None = None,
    drop_redacted: bool = False,
    commit: bool = False,
) -> ReplayResult:
    """Re-run the captured ``record`` (see the module docstring)."""
    if not getattr(settings, "DEBUG", False):
        raise KarniCommandError(
            "karni replay runs only with DEBUG on: it re-sends a captured request, as a "
            "captured user, against this database. Use it in development (DEBUG=true).",
            code="E920",
        )
    from rest_framework.test import APIClient

    body = json.loads(json.dumps(record.get("body")))
    query: dict[str, list[str]] = {
        str(name): list(values) for name, values in (record.get("query") or {}).items()
    }
    for path, raw in (sets or {}).items():
        value = _parse_value(raw)
        if path.startswith("query:"):
            query[path.removeprefix("query:")] = [value if isinstance(value, str) else raw]
        else:
            body = _set_path(body, path, value)
    remaining = redacted_paths({"body": body, "query": query})
    if remaining and not drop_redacted:
        flags = " ".join(f"--set {path}=<value>" for path in remaining)
        raise KarniCommandError(
            "These values were redacted when the request was captured, so they cannot be "
            f"replayed: {', '.join(remaining)}. Supply them ({flags}) or leave them out "
            "(--drop-redacted).",
            code="E923",
        )
    for path in remaining:
        if path.startswith("query:"):
            query.pop(path.removeprefix("query:"), None)
        else:
            _drop_path(body, path)

    user = None if anonymous else (resolve_user(as_user) if as_user else _captured_user(record))
    kwargs, notes = _request_kwargs(record, body, query)
    if remaining:
        notes.append(f"left out (redacted): {', '.join(remaining)}")
    client = APIClient(raise_request_exception=False)
    if user is not None:
        client.force_authenticate(user=user)
    method = str(record.get("method") or "GET").upper()
    path = str(record.get("path") or "/")
    emails: list[dict[str, Any]] = []
    with ExitStack() as stack:
        outbox = None if commit else stack.enter_context(_rolled_back())
        response = client.generic(method, path, **kwargs)
        if outbox is not None:
            emails = [
                {"to": list(message.to), "subject": str(message.subject)} for message in outbox
            ]
    from karni.debug import store
    from karni.tracing import REQUEST_ID_HEADER

    new_id = response.get(REQUEST_ID_HEADER)
    new_record = store.read_request(new_id) if new_id else None
    return ReplayResult(
        request_id=str(record.get("request_id")),
        method=method,
        path=path,
        user=_label(user),
        was_status=record.get("status"),
        status=int(response.status_code),
        excerpt=_excerpt(response),
        committed=commit,
        new_request_id=new_id,
        failure_id=(new_record or {}).get("failure_id"),
        emails=emails,
        notes=notes,
    )


def render(result: ReplayResult) -> str:
    """What ``karni replay`` prints."""
    mode = "committed" if result.committed else "rolled back"
    lines = [
        f"Replayed {result.method} {result.path} as {result.user} ({mode})",
        f"  {result.change}",
    ]
    if result.excerpt:
        lines.append(f"  body: {result.excerpt}")
    if result.failure_id:
        lines.append(f"  failed again: karni explain --failure {result.failure_id}")
    if result.new_request_id:
        lines.append(f"  new request {result.new_request_id}: karni trace {result.new_request_id}")
    for email in result.emails:
        lines.append(f'  email (not sent): to {", ".join(email["to"])} "{email["subject"]}"')
    for note in result.notes:
        lines.append(f"  note: {note}")
    return "\n".join(lines)
