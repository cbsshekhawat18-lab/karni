"""A failure snapshot as a brief: who asked for what, where it broke, the SQL, what to do next.

:func:`render` is what ``karni explain --failure <id>`` prints (``--json``
prints the snapshot itself). :func:`resolve_failure` accepts a failure id,
a request id whose request failed, or ``last``.
"""

from __future__ import annotations

import json
from typing import Any

from karni.exceptions import KarniCommandError

__all__ = ["render", "resolve_failure"]

#: (exception type substring, message substring, hint) — first match wins.
_HINTS: tuple[tuple[str, str, str], ...] = (
    ("OperationalError", "no such table", "A table is missing: run `karni migrate`."),
    ("ProgrammingError", "does not exist", "A table or column is missing: run `karni migrate`."),
    (
        "OperationalError",
        "no such column",
        "A column is missing: `karni make migration && karni migrate`.",
    ),
    (
        "IntegrityError",
        "",
        "A database constraint refused the write (unique, not-null or a foreign key): "
        "check the values the request sent against the model's constraints.",
    ),
    (
        "FieldError",
        "",
        "A query or serializer names a field the model does not have: check the "
        "field names in the frame above against the model.",
    ),
    (
        "DoesNotExist",
        "",
        "A .get() found no row: the row is missing or a scope (soft delete, "
        "access) hides it. Use the viewset's get_object() for API lookups.",
    ),
    ("MultipleObjectsReturned", "", "A .get() matched several rows: filter on a unique field."),
    (
        "AttributeError",
        "NoneType",
        "Something was None where the code expected an object: check "
        "the locals above for the None.",
    ),
    (
        "KeyError",
        "",
        "A dict lookup missed: check the keys in the locals above (request data, settings).",
    ),
)


def resolve_failure(value: str) -> dict[str, Any]:
    """The snapshot for a failure id, a failed request's id, or ``last``."""
    from karni.debug import store
    from karni.debug.trace import NO_CAPTURE_HINT

    failure_id: str | None = value
    if value == "last":
        failure_id = store.latest(store.failures_dir())
        if failure_id is None:
            raise KarniCommandError(
                f"No failure has been captured yet. {NO_CAPTURE_HINT}", code="E922"
            )
    snapshot = store.read_failure(str(failure_id))
    if snapshot is None:
        record = store.read_request(value)
        if record is not None and record.get("failure_id"):
            snapshot = store.read_failure(str(record["failure_id"]))
        elif record is not None:
            raise KarniCommandError(
                f"Request {value} did not fail (status {record.get('status')}), so there is no "
                f"failure snapshot for it. Follow it with `karni trace {value}`.",
                code="E922",
            )
    if snapshot is None:
        raise KarniCommandError(
            f"No failure snapshot {value!r} under .karni/failures/. Snapshots are written on an "
            f"unhandled exception, and the newest {store.keep_count()} are kept. {NO_CAPTURE_HINT}",
            code="E922",
        )
    return snapshot


def _value(value: Any, width: int = 160) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _who(user: dict[str, Any] | None) -> str:
    if not user:
        return "anonymous"
    name = user.get("email") or user.get("username") or f"user {user.get('id')}"
    flags = [flag for flag in ("is_superuser", "is_staff") if user.get(flag)]
    roles = user.get("roles")
    parts = [f"id {user.get('id')}"]
    if roles:
        parts.append("roles " + ", ".join(roles))
    elif roles == []:
        parts.append("no roles")
    parts += [flag.removeprefix("is_") for flag in flags]
    return f"{name} ({'; '.join(parts)})"


def _hint(exception: dict[str, Any]) -> str | None:
    kind = str(exception.get("type") or "")
    message = str(exception.get("message") or "")
    for type_part, message_part, hint in _HINTS:
        if type_part in kind and message_part.lower() in message.lower():
            return hint
    return None


def _as_user(user: dict[str, Any] | None) -> str:
    if not user:
        return " --anonymous"
    return f" --as {user.get('email') or user.get('username') or user.get('id')}"


def render(snapshot: dict[str, Any]) -> str:
    """The brief ``karni explain --failure`` prints."""
    lines: list[str] = []
    exception = snapshot.get("exception") or {}
    rid = snapshot.get("request_id")
    request = snapshot.get("request")
    task = snapshot.get("task")
    user = snapshot.get("user")
    if request:
        lines.append(
            f"Failure {snapshot['id']}: {request['method']} {request['path']} by {_who(user)}"
        )
    elif task:
        lines.append(
            f"Failure {snapshot['id']}: task {task['name']} [{task.get('id')}] after "
            f"{task.get('retries', 0)} retries"
        )
    else:
        lines.append(f"Failure {snapshot['id']}")
    lines.append(f"  at {snapshot.get('at')}  request {rid or '-'}")
    lines.append("")
    lines.append(f"Exception: {exception.get('type')}: {_value(exception.get('message'), 400)}")
    for link in exception.get("chain") or []:
        lines.append(f"  from {link['type']}: {_value(link['message'], 300)}")
    code = exception.get("error_code")
    lines.append(f"Karni code: {code} (karni explain {code})" if code else "Karni code: none")

    frames = snapshot.get("frames") or []
    origin = snapshot.get("origin")
    if origin is not None and 0 <= origin < len(frames):
        frame = frames[origin]
        lines.append("")
        lines.append(
            f"Where: {frame['file']}:{frame['line']} in {frame['function']} ({frame['kind']})"
        )
        if frame.get("code"):
            lines.append(f"    {frame['line']} | {frame['code']}")
        local_items = list((frame.get("locals") or {}).items())
        if local_items:
            lines.append("  locals:")
            for name, value in local_items[:20]:
                lines.append(f"    {name} = {_value(value)}")
    else:
        lines.append("")
        lines.append("Where: no Karni or project frame in the traceback (a library raised).")
    path = [f for f in frames if f.get("kind") != "library"]
    if len(path) > 1:
        lines.append("  call path (project and Karni frames, outermost first):")
        for frame in path[-8:]:
            lines.append(f"    {frame['file']}:{frame['line']} in {frame['function']}")

    view = snapshot.get("view")
    if view and view.get("view"):
        detail = ", ".join(f"{key} {view[key]}" for key in ("resource", "action") if view.get(key))
        lines.append("")
        lines.append(f"View: {view['view']}" + (f" ({detail})" if detail else ""))
        if view.get("serializer"):
            lines.append(f"  serializer {view['serializer']}")
        if view.get("kwargs"):
            lines.append(f"  kwargs {_value(view['kwargs'])}")
    if task:
        lines.append("")
        lines.append(f"Task arguments: {_value(task.get('arguments'))}")
    if user and user.get("grants") is not None:
        grants = user["grants"]
        shown = "; ".join(f"{key}: {', '.join(scopes)}" for key, scopes in list(grants.items())[:8])
        lines.append(f"Grants: {shown or 'none on this resource'}")
    if request and request.get("body") not in (None, {}, ""):
        lines.append(f"Body: {_value(request['body'])}")

    queries = snapshot.get("queries")
    duplicates: list[dict[str, Any]] = []
    if queries:
        duplicates = queries.get("duplicates") or []
        lines.append("")
        lines.append(
            f"Queries: {queries['count']} in {queries['total_ms']} ms, "
            f"{len(duplicates)} repeated statement{'s' if len(duplicates) != 1 else ''}"
        )
        for group in duplicates[:5]:
            origin_text = f"  <- {group['origin']}" if group.get("origin") else ""
            lines.append(f"  {group['count']}x {_value(group['sql'], 120)}{origin_text}")

    lines.append("")
    lines.append("Next steps:")
    steps: list[str] = []
    if origin is not None and 0 <= origin < len(frames):
        frame = frames[origin]
        steps.append(
            f"Open {frame['file']}:{frame['line']} ({frame['function']}): it raised there."
        )
    if code:
        steps.append(f"`karni explain {code}` says why Karni objects and the exact fix.")
    hint = _hint(exception)
    if hint:
        steps.append(hint)
    if duplicates:
        steps.append(
            "Repeated statements are an N+1: add select_related/prefetch_related where the "
            "origin points (or let the viewset optimizer see the relation)."
        )
    if request and rid:
        steps.append(
            f"After the fix: `karni replay {rid}{_as_user(user)}` re-runs this request "
            "against the current code (was 500)."
        )
    if rid:
        steps.append(f"`karni trace {rid}` shows what else the request set in motion.")
    for number, step in enumerate(steps, 1):
        lines.append(f"  {number}. {step}")
    return "\n".join(lines)
