"""The ``.karni/`` capture directory: where records go, how they are written, read and pruned.

Layout (under the project root — ``settings.BASE_DIR``, else the directory
above the settings package)::

    .karni/requests/<request_id>.json     one request record (contract version 1)
    .karni/failures/<failure_id>.json     one failure snapshot
    .karni/trace/<YYYY-MM-DD>.jsonl       trace events, one JSON object per line

Each of the three directories carries its own ``.gitignore`` (``*``), so the
captures stay out of git even in a project whose ``.gitignore`` predates them.
Records are written to a temporary file and renamed into place, so a reader
never sees half a file; trace lines are appended with one ``write`` each
(``O_APPEND``), so the web process and a worker can share a file.

Bounded with no configuration: the newest ``KARNI_DEBUG_CAPTURE_KEEP`` (200)
request records and failure snapshots are kept, and trace files older than
``KARNI_DEBUG_TRACE_DAYS`` (7) are deleted.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

from django.conf import settings

__all__ = [
    "append_event",
    "capture_root",
    "failures_dir",
    "iter_events",
    "latest",
    "read_failure",
    "read_request",
    "requests_dir",
    "trace_dir",
    "write_failure",
    "write_request",
]

DEFAULT_KEEP: Final = 200
DEFAULT_TRACE_DAYS: Final = 7

_pruned_trace_on: dt.date | None = None


def capture_root() -> Path:
    """``<project root>/.karni`` (the root is ``BASE_DIR``, else the settings package's parent)."""
    from karni.testing._source import project_root

    return project_root() / ".karni"


def requests_dir() -> Path:
    return capture_root() / "requests"


def failures_dir() -> Path:
    return capture_root() / "failures"


def trace_dir() -> Path:
    return capture_root() / "trace"


def keep_count() -> int:
    return max(1, int(getattr(settings, "KARNI_DEBUG_CAPTURE_KEEP", DEFAULT_KEEP) or DEFAULT_KEEP))


def _trace_days() -> int:
    days = getattr(settings, "KARNI_DEBUG_TRACE_DAYS", DEFAULT_TRACE_DAYS)
    return max(1, int(days or DEFAULT_TRACE_DAYS))


def _ensure(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    ignore = directory / ".gitignore"
    if not ignore.exists():
        ignore.write_text("# Karni development capture (DEBUG only); never committed.\n*\n")
    return directory


def dumps(data: Any, *, indent: int | None = None) -> str:
    """JSON text (non-JSON values as strings)."""
    return json.dumps(data, indent=indent, default=str, ensure_ascii=False)


def _write_json(directory: Path, name: str, data: Any) -> Path:
    _ensure(directory)
    target = directory / f"{name}.json"
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(dumps(data, indent=2))
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    _prune(directory, keep_count())
    return target


def _prune(directory: Path, keep: int) -> None:
    files = [path for path in directory.glob("*.json") if not path.name.startswith(".")]
    if len(files) <= keep:
        return
    files.sort(key=lambda path: path.stat().st_mtime)
    for path in files[: len(files) - keep]:
        path.unlink(missing_ok=True)


def write_request(record: dict[str, Any]) -> Path:
    """Write ``.karni/requests/<request_id>.json``."""
    return _write_json(requests_dir(), str(record["request_id"]), record)


def write_failure(snapshot: dict[str, Any]) -> Path:
    """Write ``.karni/failures/<id>.json``."""
    return _write_json(failures_dir(), str(snapshot["id"]), snapshot)


def now_iso() -> str:
    """The current UTC time, ISO-8601 with microseconds."""
    return dt.datetime.now(dt.UTC).isoformat()


def append_event(
    event: str, request_id: str, *, refs: list[str] | None, fields: dict[str, Any]
) -> None:
    """Append one trace line (fields redacted) to today's file; prune old files daily."""
    from karni.debug import TRACE_VERSION
    from karni.debug.redact import active_redactor

    redactor = active_redactor()
    line: dict[str, Any] = {
        "v": TRACE_VERSION,
        "at": now_iso(),
        "request_id": request_id,
        "event": event,
        "pid": os.getpid(),
    }
    for name, value in fields.items():
        if value is not None:
            line[name] = redactor.value(_jsonable(value), key=name)
    if refs:
        line["refs"] = [str(ref) for ref in refs]
    directory = _ensure(trace_dir())
    path = directory / f"{dt.datetime.now(dt.UTC):%Y-%m-%d}.jsonl"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(dumps(line) + "\n")
    _prune_trace()


def _jsonable(value: Any) -> Any:
    from karni.audit.capture import json_value

    return json_value(value)


def _prune_trace() -> None:
    global _pruned_trace_on
    today = dt.datetime.now(dt.UTC).date()
    if _pruned_trace_on == today:
        return
    _pruned_trace_on = today
    cutoff = today - dt.timedelta(days=_trace_days())
    for path in trace_dir().glob("*.jsonl"):
        try:
            day = dt.date.fromisoformat(path.stem)
        except ValueError:
            continue
        if day < cutoff:
            path.unlink(missing_ok=True)


# --- reading -----------------------------------------------------------------


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _safe_name(value: str) -> bool:
    from karni.tracing import is_valid_request_id

    return is_valid_request_id(value)


def read_request(request_id: str) -> dict[str, Any] | None:
    """The request record for ``request_id``, or ``None``."""
    if not _safe_name(request_id):
        return None
    return _read(requests_dir() / f"{request_id}.json")


def read_failure(failure_id: str) -> dict[str, Any] | None:
    """The failure snapshot ``failure_id``, or ``None``."""
    if not _safe_name(failure_id):
        return None
    return _read(failures_dir() / f"{failure_id}.json")


def latest(directory: Path) -> str | None:
    """The name (without ``.json``) of the newest record in ``directory``."""
    files = [path for path in directory.glob("*.json") if not path.name.startswith(".")]
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime).stem


def iter_events(request_ids: set[str] | None = None) -> Iterator[dict[str, Any]]:
    """Every trace event (of ``request_ids`` when given), oldest file first."""
    directory = trace_dir()
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.jsonl")):
        try:
            handle = open(path, encoding="utf-8")  # noqa: SIM115 - closed below
        except OSError:
            continue
        with handle:
            for raw in handle:
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                if request_ids is None or event.get("request_id") in request_ids:
                    yield event
