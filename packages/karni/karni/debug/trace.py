"""Reassemble one request's story: its events, its async work and its audit entries, in order.

:func:`story` reads ``.karni/trace/*.jsonl`` (every event carrying the id —
the request, the tasks it enqueued and their retries minutes later, email,
webhooks), the request record, and the change log (``ChangeLog`` and
``ChangeBatch`` rows with that ``request_id``; the database is optional —
when it cannot be read, the story says so and goes on). Requests whose
events share a ref (``karni_payments.Payment:<pk>``) with this one are
listed as linked: the checkout and the webhook that settled it.
:func:`render` is what ``karni trace`` prints; ``--json`` prints the dict.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from karni.exceptions import KarniCommandError

__all__ = ["NO_CAPTURE_HINT", "render", "resolve_request_id", "story"]

NO_CAPTURE_HINT = (
    "Capture runs only with DEBUG on (and KARNI_DEBUG_CAPTURE not False); it writes "
    ".karni/requests/, .karni/failures/ and .karni/trace/ under the project root. Turn "
    "DEBUG on, repeat the request, and take the id from its X-Request-ID response header "
    "(or use `last`)."
)


def resolve_request_id(value: str) -> str:
    """``value`` itself, or the newest captured request id for ``last``."""
    from karni.debug import store
    from karni.tracing import is_valid_request_id

    if value == "last":
        found = store.latest(store.requests_dir())
        if found is None:
            raise KarniCommandError(
                f"No request has been captured yet. {NO_CAPTURE_HINT}", code="E921"
            )
        return found
    if not is_valid_request_id(value):
        raise KarniCommandError(
            f"{value!r} is not a request id: ids are 1-128 letters, digits, '_' and '-' "
            "(the X-Request-ID response header), or `last`.",
            code="E921",
        )
    return value


def _parse_at(value: Any) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(str(value))
    except ValueError:
        return dt.datetime.min.replace(tzinfo=dt.UTC)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def _audit(request_id: str) -> tuple[list[dict[str, Any]], str | None]:
    """Change log entries and batches with this request id, as timeline events."""
    try:
        from karni.audit.models import ChangeBatch, ChangeLog

        found: list[dict[str, Any]] = []
        for batch in ChangeBatch.objects.filter(request_id=request_id).order_by("timestamp"):
            found.append(
                {
                    "at": batch.timestamp.isoformat(),
                    "event": "audit.batch",
                    "source": "database",
                    "batch_id": batch.pk,
                    "kind": batch.kind,
                    "label": batch.label,
                }
            )
        entries = (
            ChangeLog.objects.filter(request_id=request_id)
            .select_related("content_type")
            .order_by("timestamp", "id")
        )
        for entry in entries:
            content_type = entry.content_type
            found.append(
                {
                    "at": entry.timestamp.isoformat(),
                    "event": "audit.change",
                    "source": "database",
                    "action": entry.action,
                    "object": f"{content_type.app_label}.{content_type.model}:{entry.object_id}",
                    "fields": entry.fields_changed,
                    "actor_id": str(entry.actor_id) if entry.actor_id is not None else None,
                    "batch_id": entry.batch_id,
                }
            )
        return found, None
    except Exception as exc:  # noqa: BLE001 - the files tell most of the story without the DB
        return [], f"change log not read ({type(exc).__name__}: {str(exc)[:200]})"


def _linked(request_id: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from karni.debug import store

    refs = {str(ref) for event in events for ref in event.get("refs") or ()}
    if not refs:
        return []
    found: dict[str, dict[str, Any]] = {}
    for event in store.iter_events():
        other = event.get("request_id")
        shared = refs & {str(ref) for ref in event.get("refs") or ()}
        if not other or other == request_id or not shared:
            continue
        entry = found.setdefault(
            str(other),
            {"request_id": other, "at": event.get("at"), "events": [], "refs": []},
        )
        entry["events"].append(event.get("event"))
        entry["refs"] = sorted(set(entry["refs"]) | shared)
    for entry in found.values():
        record = store.read_request(entry["request_id"])
        entry["request"] = f"{record['method']} {record['path']}" if record else None
    return sorted(found.values(), key=lambda entry: _parse_at(entry["at"]))


def _summary(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if record is None:
        return None
    keys = ("method", "path", "status", "duration_ms", "view", "resource", "action", "user")
    summary = {key: record.get(key) for key in keys}
    summary.update(
        at=record.get("at"),
        error_code=record.get("error_code"),
        failure_id=record.get("failure_id"),
    )
    return summary


def story(request_id: str, *, with_audit: bool = True) -> dict[str, Any] | None:
    """Everything captured about ``request_id``, oldest first; ``None`` when nothing was."""
    from karni.debug import store

    events = [dict(event, source="trace") for event in store.iter_events({request_id})]
    record = store.read_request(request_id)
    audit, audit_note = _audit(request_id) if with_audit else ([], None)
    if not events and record is None and not audit:
        return None
    timeline = sorted(events + audit, key=lambda event: _parse_at(event.get("at")))
    return {
        "request_id": request_id,
        "request": _summary(record),
        "events": timeline,
        "linked": _linked(request_id, events),
        "notes": [audit_note] if audit_note else [],
    }


# --- rendering -----------------------------------------------------------------


def _offset(seconds: float) -> str:
    if seconds < 60:
        return f"+{seconds:.3f}s"
    minutes, rest = divmod(seconds, 60)
    return f"+{int(minutes)}m{rest:04.1f}s"


def _short(task_id: Any) -> str:
    return f"[{str(task_id)[:8]}]" if task_id else ""


_SKIP = {"v", "at", "request_id", "event", "pid", "source", "refs"}


def describe(event: dict[str, Any]) -> str:
    """One event as a short line of text."""
    name = event.get("event")
    get = event.get
    if name == "request.start":
        replay = f" (replay of {get('replay_of')})" if get("replay_of") else ""
        return f"{get('method')} {get('path')}{replay}"
    if name == "request.end":
        extra = ""
        if get("error_code"):
            extra += f" code {get('error_code')}"
        if get("failure_id"):
            extra += f" failure {get('failure_id')}"
        return f"{get('status')} in {get('duration_ms')} ms{extra}"
    if name and str(name).startswith("task."):
        line = f"{get('task')} {_short(get('task_id'))}"
        if get("retries"):
            line += f" retry {get('retries')}"
        if name == "task.started":
            line += " (eager, in the request)" if get("eager") else f" (pid {get('pid')})"
        if name == "task.enqueued" and get("eta"):
            line += f" eta {get('eta')}"
        if name == "task.retried" and get("reason"):
            line += f": {get('reason')}"
        if get("duration_ms") is not None:
            line += f" in {get('duration_ms')} ms"
        if name == "task.failed":
            line += f" — {get('exception')}: {get('message')}"
            if get("failure_id"):
                line += f" (failure {get('failure_id')})"
        return line
    if name == "email.sent":
        to = ", ".join(get("to") or [])
        return f'to {to} "{get("subject")}"'
    if name == "audit.change":
        fields = ", ".join(get("fields") or [])
        return f"{get('action')} {get('object')} ({fields})"
    if name == "audit.batch":
        return f"{get('kind')} {get('label') or ''} (batch {get('batch_id')})".replace("  ", " ")
    parts = [f"{key}={event[key]}" for key in event if key not in _SKIP]
    if event.get("refs"):
        parts.append("refs=" + ",".join(event["refs"]))
    return " ".join(parts)


def render(data: dict[str, Any]) -> str:
    """The person-readable story ``karni trace`` prints."""
    lines: list[str] = []
    rid = data["request_id"]
    request = data.get("request")
    if request:
        user = request.get("user") or {}
        who = user.get("email") or user.get("username") or user.get("id") or "anonymous"
        lines.append(
            f"Request {rid}: {request['method']} {request['path']} -> {request['status']} "
            f"in {request['duration_ms']} ms, as {who}"
        )
        view = request.get("view") or "(no view matched)"
        detail = ", ".join(
            str(part) for part in (request.get("resource"), request.get("action")) if part
        )
        lines.append(f"  view  {view}" + (f" ({detail})" if detail else ""))
        if request.get("failure_id"):
            lines.append(f"  failed: karni explain --failure {request['failure_id']}")
    else:
        lines.append(f"Request {rid} (no request record: async work or a pruned record)")
    events = data.get("events") or []
    if events:
        start = _parse_at(events[0].get("at"))
        lines.append(f"  started {start:%Y-%m-%d %H:%M:%S} UTC")
        lines.append("")
        width = max(len(str(event.get("event"))) for event in events)
        for event in events:
            offset = _offset((_parse_at(event.get("at")) - start).total_seconds())
            name = str(event.get("event")).ljust(width)
            lines.append(f"  {offset:>10}  {name}  {describe(event)}")
    linked = data.get("linked") or []
    if linked:
        lines.append("")
        lines.append("Linked requests (their events name the same rows):")
        for entry in linked:
            what = entry.get("request") or "async work"
            lines.append(
                f"  {entry['request_id']}  {what}  {', '.join(entry['events'])}  "
                f"[{', '.join(entry['refs'])}]"
            )
    for note in data.get("notes") or []:
        lines.append("")
        lines.append(f"Note: {note}")
    return "\n".join(lines)
