"""Failure snapshots: everything an agent needs about one crash, in ``.karni/failures/<id>.json``.

Written on an unhandled exception in a request (``got_request_exception``)
or a Celery task (``task_failure``), in development only. Format version 1::

    {"version": 1, "id": str, "at": ISO-8601, "request_id": str | null,
     "kind": "request" | "task",
     "request": {"method", "path", "query", "headers", "body", "content_type"} | null,
     "task": {"name", "id", "retries", "arguments": {name: value}} | null,
     "view": {"view", "viewset", "resource", "action", "serializer", "kwargs"} | null,
     "user": {"id", "email", "username", "is_staff", "is_superuser",
              "roles": [str], "grants": {"app.model:action": [scope]}} | null,
     "exception": {"type", "message", "error_code", "chain": [{"type", "message"}]},
     "frames": [{"file", "line", "function", "module", "code", "kind", "locals"}],
     "origin": int | null,
     "queries": {"count", "total_ms", "duplicates": [{"sql", "count", "total_ms", "origin"}],
                 "statements": [{"sql", "ms"}]} | null,
     "settings": {"DEBUG", "DATABASES", "INSTALLED_APPS", "KARNI": {...}},
     "versions": {"python", "django", "djangorestframework", "karni"}}

``frames`` run outermost first. ``kind`` is ``project`` (a file under the
project root), ``karni`` (Karni or a Karni module) or ``library``; only the
first two carry ``locals`` (each value rendered safely and truncated: no
database access, no queryset evaluation). ``origin`` indexes the frame where
it failed: the innermost project frame, else the innermost Karni frame. SQL
is the statement text with placeholders (parameters are never recorded).
Everything passes :mod:`karni.debug.redact`.
"""

from __future__ import annotations

import logging
import platform
import re
import sys
import traceback as tb_module
import uuid
from collections.abc import Mapping
from pathlib import Path
from types import FrameType, TracebackType
from typing import TYPE_CHECKING, Any, Final

from django.conf import settings

if TYPE_CHECKING:
    from karni.debug.middleware import Capture
    from karni.debug.redact import Redactor

__all__ = ["FAILURE_VERSION", "build_settings", "capture_request_failure", "capture_task_failure"]

logger = logging.getLogger("karni.debug")

FAILURE_VERSION: Final = 1

_MAX_FRAMES: Final = 60
_MAX_LOCALS: Final = 40
_MAX_STR: Final = 500
_MAX_ITEMS: Final = 20
_MAX_DEPTH: Final = 3
_MAX_STATEMENTS: Final = 200
_CODE_IN_TEXT: Final = re.compile(r"\b((?:[EW]\d{3})|(?:[A-Z]{2,5}\d{3}))\b")


def new_failure_id() -> str:
    """A short id people can type: 12 hex digits."""
    return uuid.uuid4().hex[:12]


# --- frames ------------------------------------------------------------------


def _site_roots() -> tuple[str, ...]:
    import sysconfig

    roots = {sysconfig.get_paths()["stdlib"], sysconfig.get_paths()["purelib"]}
    roots.update(path for path in sys.path if "site-packages" in path or "dist-packages" in path)
    return tuple(sorted(str(Path(root).resolve()) for root in roots if root))


def _project_root() -> Path:
    from karni.testing._source import project_root

    return project_root()


def frame_kind(module: str, filename: str, root: str, site: tuple[str, ...]) -> str:
    """``karni`` (Karni and its modules), ``project`` (the project's files) or ``library``."""
    if module == "karni" or module.startswith(("karni.", "karni_")):
        return "karni"
    if filename.startswith("<"):
        return "library"
    resolved = str(Path(filename).resolve())
    if resolved.startswith(root) and not any(resolved.startswith(prefix) for prefix in site):
        parts = Path(resolved).parts
        if ".venv" not in parts and "venv" not in parts and "node_modules" not in parts:
            return "project"
    return "library"


def _relative(filename: str, root: Path) -> str:
    """Relative to the project root, else to the ``sys.path`` entry it imports from."""
    resolved = Path(filename).resolve()
    for base in (root, *sorted((Path(p) for p in sys.path if p), key=lambda p: -len(str(p)))):
        try:
            return str(resolved.relative_to(base.resolve()))
        except (ValueError, OSError):
            continue
    return filename


def _source_line(filename: str, lineno: int) -> str:
    import linecache

    return linecache.getline(filename, lineno).strip()


def render_value(value: Any, redactor: Redactor, depth: int = 0) -> Any:
    """A JSON-safe, truncated, redacted rendering of any object — never touches the database."""
    from django.db import models
    from django.db.models.query import QuerySet
    from django.http import HttpRequest

    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        text = redactor.scrub(value)
        return text if len(text) <= _MAX_STR else f"{text[:_MAX_STR]}… ({len(text)} chars)"
    if isinstance(value, bytes):
        return f"<bytes, {len(value)}>"
    if depth >= _MAX_DEPTH:
        return f"<{type(value).__name__}>"
    if isinstance(value, Mapping):
        items = list(value.items())
        out = {
            str(key): render_value(item, redactor, depth + 1)
            if not redactor.sensitive(key)
            else "[redacted]"
            for key, item in items[:_MAX_ITEMS]
        }
        if len(items) > _MAX_ITEMS:
            out["…"] = f"{len(items) - _MAX_ITEMS} more"
        return out
    if isinstance(value, list | tuple | set | frozenset):
        seq = list(value)
        rendered = [render_value(item, redactor, depth + 1) for item in seq[:_MAX_ITEMS]]
        if len(seq) > _MAX_ITEMS:
            rendered.append(f"… {len(seq) - _MAX_ITEMS} more")
        return rendered
    if isinstance(value, models.Model):
        return _render_model(value, redactor)
    if isinstance(value, QuerySet):
        cached = value._result_cache
        rows = f", {len(cached)} rows fetched" if cached is not None else ", not evaluated"
        return f"<QuerySet {value.model._meta.label}{rows}>"
    if isinstance(value, HttpRequest) or type(value).__name__ == "Request":
        method = getattr(value, "method", "")
        path = getattr(value, "path", "")
        return f"<{type(value).__name__} {method} {path}>"
    lazy = getattr(value, "_wrapped", None)
    if lazy is not None and type(value).__name__ in {"SimpleLazyObject", "LazyObject"}:
        from django.utils.functional import empty

        if lazy is empty:
            return f"<{type(value).__name__}, not evaluated>"
        value = lazy
        if isinstance(value, models.Model):
            return _render_model(value, redactor)
    try:
        text = repr(value)
    except Exception as exc:  # noqa: BLE001 - a broken __repr__ must not break the snapshot
        text = f"<{type(value).__name__}: repr failed ({type(exc).__name__})>"
    text = redactor.scrub(text)
    return text if len(text) <= _MAX_STR else f"{text[:_MAX_STR]}…"


def _render_model(instance: Any, redactor: Redactor) -> dict[str, Any]:
    from karni.audit.capture import json_value, sensitive_fields

    model = type(instance)
    hidden = sensitive_fields(model)
    found: dict[str, Any] = {"__model__": model._meta.label, "pk": json_value(instance.pk)}
    for model_field in model._meta.concrete_fields[:_MAX_ITEMS]:
        name = model_field.name
        if name in hidden or redactor.sensitive(name):
            found[name] = "[redacted]"
            continue
        raw = instance.__dict__.get(model_field.attname)
        found[name] = render_value(json_value(raw), redactor, _MAX_DEPTH - 1)
    return found


def _frame_locals(frame: FrameType, redactor: Redactor) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for index, (name, value) in enumerate(frame.f_locals.items()):
        if index >= _MAX_LOCALS:
            out["…"] = f"{len(frame.f_locals) - _MAX_LOCALS} more"
            break
        if name.startswith("__") and name.endswith("__"):
            continue
        out[name] = "[redacted]" if redactor.sensitive(name) else render_value(value, redactor)
    return out


def build_frames(
    traceback: TracebackType | None, redactor: Redactor
) -> tuple[list[dict[str, Any]], int | None]:
    """The traceback outermost first, with locals for project and Karni frames, plus the origin."""
    root = _project_root()
    root_text = str(root.resolve())
    site = _site_roots()
    entries: list[tuple[FrameType, int]] = []
    current = traceback
    while current is not None:
        entries.append((current.tb_frame, current.tb_lineno))
        current = current.tb_next
    skipped = max(0, len(entries) - _MAX_FRAMES)
    frames: list[dict[str, Any]] = []
    for frame, lineno in entries[skipped:]:
        code = frame.f_code
        module = str(frame.f_globals.get("__name__", ""))
        kind = frame_kind(module, code.co_filename, root_text, site)
        item: dict[str, Any] = {
            "file": _relative(code.co_filename, root),
            "line": lineno,
            "function": code.co_qualname if hasattr(code, "co_qualname") else code.co_name,
            "module": module,
            "code": redactor.scrub(_source_line(code.co_filename, lineno)),
            "kind": kind,
        }
        if kind != "library":
            item["locals"] = _frame_locals(frame, redactor)
        frames.append(item)
    origin = None
    for wanted in ("project", "karni"):
        for index in range(len(frames) - 1, -1, -1):
            if frames[index]["kind"] == wanted:
                origin = index
                break
        if origin is not None:
            break
    return frames, origin


def _exception(exc: BaseException, redactor: Redactor) -> dict[str, Any]:
    chain: list[dict[str, Any]] = []
    seen = {id(exc)}
    current = exc.__cause__ or exc.__context__
    while current is not None and id(current) not in seen and len(chain) < 5:
        seen.add(id(current))
        chain.append({"type": _type_name(current), "message": redactor.scrub(str(current))[:1000]})
        current = current.__cause__ or current.__context__
    message = redactor.scrub(str(exc))
    code = getattr(exc, "code", None)
    if not (isinstance(code, str) and _CODE_IN_TEXT.fullmatch(code)):
        match = _CODE_IN_TEXT.search(message)
        code = match.group(1) if match else None
    return {
        "type": _type_name(exc),
        "message": message[:2000],
        "error_code": code,
        "chain": chain,
        "traceback": redactor.scrub("".join(tb_module.format_exception_only(type(exc), exc)))[
            :2000
        ],
    }


def _type_name(exc: BaseException) -> str:
    cls = type(exc)
    module = cls.__module__
    return cls.__qualname__ if module == "builtins" else f"{module}.{cls.__qualname__}"


# --- request parts -----------------------------------------------------------


def _queries(recorder: Any, redactor: Redactor) -> dict[str, Any] | None:
    if recorder is None:
        return None
    report = recorder.report()
    statements = [
        {"sql": redactor.scrub(" ".join(query.sql.split())), "ms": round(query.duration * 1000, 3)}
        for query in report.queries[:_MAX_STATEMENTS]
    ]
    duplicates = [
        {
            "sql": redactor.scrub(" ".join(group.sql.split())),
            "count": group.count,
            "total_ms": round(group.duration * 1000, 3),
            "origin": group.origin,
        }
        for group in report.duplicates()
    ]
    return {
        "count": report.count,
        "total_ms": round(report.duration * 1000, 3),
        "duplicates": duplicates,
        "statements": statements,
    }


def _view_instance(traceback: TracebackType | None, cls: Any) -> Any:
    if cls is None:
        return None
    current = traceback
    while current is not None:
        candidate = current.tb_frame.f_locals.get("self")
        if isinstance(candidate, cls):
            return candidate
        current = current.tb_next
    return None


def _view(capture: Capture, traceback: TracebackType | None) -> dict[str, Any]:
    from karni.debug.middleware import dotted, view_identity

    identity = view_identity(capture.view_func, capture.request.method or "GET")
    viewset = identity.pop("viewset")
    serializer = None
    instance = _view_instance(traceback, viewset)
    if instance is not None and hasattr(instance, "get_serializer_class"):
        try:
            serializer = dotted(instance.get_serializer_class())
        except Exception:  # noqa: BLE001 - the serializer lookup may be what failed
            serializer = None
    if instance is not None and getattr(instance, "action", None):
        identity["action"] = identity["action"] or str(instance.action)
    identity["viewset"] = dotted(viewset) if viewset is not None else None
    identity["serializer"] = serializer
    identity["kwargs"] = {
        str(name): capture.redactor.scrub(str(value)) for name, value in capture.view_kwargs.items()
    }
    return identity


def user_details(user: Any, redactor: Redactor, model: Any = None) -> dict[str, Any] | None:
    """The user record plus roles and the grants on ``model`` (all grants without one)."""
    from karni.debug.middleware import user_record

    record = user_record(user)
    if record is None:
        return None
    try:
        from karni.accounts.permissions import user_roles
        from karni.accounts.roles import grants_for

        record["roles"] = user_roles(user)
        grants = grants_for(user)
        prefix = f"{model._meta.label_lower}:" if model is not None else ""
        record["grants"] = {
            key: sorted(
                {
                    grant.scope + (f":{grant.scope_path}" if grant.scope_path else "")
                    for grant in found
                }
            )
            for key, found in sorted(grants.items())
            if not prefix or key.startswith(prefix)
        }
        if getattr(user, "is_superuser", False):
            record["grants"] = {"*": ["all (superuser)"]}
    except Exception as exc:  # noqa: BLE001 - a broken transaction must not lose the snapshot
        record["roles"] = None
        record["grants"] = None
        record["roles_error"] = f"{type(exc).__name__}: {exc}"[:300]
    return redactor.value(record)


def _model_of(viewset: Any) -> Any:
    model = getattr(viewset, "model", None)
    if model is None:
        queryset = getattr(viewset, "queryset", None)
        model = getattr(queryset, "model", None)
    return model


def build_settings(redactor: Redactor) -> dict[str, Any]:
    """DEBUG, database engine/name/host (never a password), project apps, every KARNI_* setting."""
    from karni.audit.capture import json_value

    databases: dict[str, Any] = {}
    for alias, config in (getattr(settings, "DATABASES", None) or {}).items():
        if isinstance(config, Mapping):
            databases[str(alias)] = {
                key: redactor.scrub(str(config.get(key) or ""))
                for key in ("ENGINE", "NAME", "HOST", "PORT")
            }
    try:
        from karni.testing._source import project_app_configs

        apps = [config.name for config in project_app_configs()]
    except Exception:  # noqa: BLE001 - the app registry may be what failed
        apps = []
    karni = {
        name: "[redacted]"
        if redactor.sensitive(name)
        else render_value(json_value(getattr(settings, name)), redactor)
        for name in sorted(dir(settings))
        if name.startswith("KARNI_")
    }
    return {
        "DEBUG": bool(getattr(settings, "DEBUG", False)),
        "DATABASES": databases,
        "INSTALLED_APPS": apps,
        "KARNI": karni,
    }


def _versions() -> dict[str, str]:
    from importlib.metadata import PackageNotFoundError, version

    found = {"python": platform.python_version()}
    for name in ("django", "djangorestframework", "karni"):
        try:
            found[name] = version(name)
        except PackageNotFoundError:
            continue
    return found


def _snapshot(
    *,
    kind: str,
    request_id: str | None,
    exc: BaseException,
    traceback: TracebackType | None,
    redactor: Redactor,
) -> dict[str, Any]:
    from karni.debug.store import now_iso

    frames, origin = build_frames(traceback, redactor)
    return {
        "version": FAILURE_VERSION,
        "id": new_failure_id(),
        "at": now_iso(),
        "request_id": request_id,
        "kind": kind,
        "request": None,
        "task": None,
        "view": None,
        "user": None,
        "exception": _exception(exc, redactor),
        "frames": frames,
        "origin": origin,
        "queries": None,
        "settings": build_settings(redactor),
        "versions": _versions(),
    }


def capture_request_failure(capture: Capture, exc: BaseException) -> str | None:
    """Write the snapshot of ``exc`` raised by the request being captured; returns its id."""
    try:
        request = capture.request
        redactor = capture.redactor
        traceback = exc.__traceback__
        from karni.debug.middleware import (
            _content_type,
            received_headers,
            render_body,
            view_identity,
        )

        # The body first (it teaches the redactor a multipart form's secrets),
        # then the SQL: the role lookups below run queries of their own.
        body = render_body(capture)
        queries = _queries(capture.recorder, redactor)
        snapshot = _snapshot(
            kind="request",
            request_id=capture.request_id,
            exc=exc,
            traceback=traceback,
            redactor=redactor,
        )
        snapshot["request"] = {
            "method": request.method,
            "path": request.path,
            "query": redactor.query(request.GET.lists()),
            "headers": redactor.headers(received_headers(request)),
            "body": body,
            "content_type": _content_type(request),
        }
        snapshot["view"] = _view(capture, traceback)
        viewset = view_identity(capture.view_func, request.method or "GET")["viewset"]
        snapshot["user"] = user_details(
            getattr(request, "user", None), redactor, _model_of(viewset)
        )
        snapshot["queries"] = queries
        from karni.debug.store import write_failure

        write_failure(snapshot)
        return str(snapshot["id"])
    except Exception:  # noqa: BLE001 - capture must never break the request
        logger.warning("karni.debug: could not write the failure snapshot", exc_info=True)
        return None


def _task_arguments(task: Any, request: Any) -> dict[str, Any]:
    """The task's arguments by parameter name, so a ``token`` argument is redacted by name."""
    import inspect

    args = list(getattr(request, "args", None) or [])
    kwargs = dict(getattr(request, "kwargs", None) or {})
    try:
        bound = inspect.signature(task.run).bind_partial(*args, **kwargs)
    except (TypeError, ValueError, AttributeError):
        return {**{f"arg{index}": value for index, value in enumerate(args)}, **kwargs}
    return dict(bound.arguments)


def capture_task_failure(
    task: Any, task_id: Any, exc: BaseException, traceback: Any = None
) -> str | None:
    """Write the snapshot of a Celery task that failed for good; returns its id."""
    try:
        from karni.debug.redact import Redactor
        from karni.tracing import get_request_id

        redactor = Redactor()
        request = getattr(task, "request", None)
        snapshot = _snapshot(
            kind="task",
            request_id=get_request_id(),
            exc=exc,
            traceback=traceback if isinstance(traceback, TracebackType) else exc.__traceback__,
            redactor=redactor,
        )
        snapshot["task"] = {
            "name": str(getattr(task, "name", "") or ""),
            "id": str(task_id) if task_id is not None else None,
            "retries": int(getattr(request, "retries", 0) or 0),
            "arguments": render_value(_task_arguments(task, request), redactor),
        }
        from karni.debug.store import write_failure

        write_failure(snapshot)
        return str(snapshot["id"])
    except Exception:  # noqa: BLE001 - capture must never break the worker
        logger.warning("karni.debug: could not write the task failure snapshot", exc_info=True)
        return None
