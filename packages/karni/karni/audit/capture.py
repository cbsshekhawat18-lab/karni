"""Capture changes at the model layer: a ``pre_save`` snapshot, then ``post_save``/``post_delete``.

Receivers are connected for every model and return at once for models that
do not opt in (``Karni.audit``), so the cost for the rest of the project is a
dictionary lookup. For an audited model a save costs one extra ``SELECT`` of
the audited columns before the write (the snapshot) and one ``INSERT`` after
it (the entry) — or a task enqueue when ``KARNI_AUDIT_ASYNC`` is on.
"""

from __future__ import annotations

import datetime as dt
import decimal
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from django.conf import settings
from django.db import models, transaction
from django.db.models.signals import post_delete, post_save, pre_save

from karni.audit import REDACTED
from karni.exceptions import KarniImproperlyConfigured
from karni.meta import karni_option
from karni.middleware import get_current_user

__all__ = [
    "DEFAULT_REDACT",
    "audited_fields",
    "change_batch",
    "clear_caches",
    "connect",
    "current_batch_id",
    "diff_values",
    "json_value",
    "record",
    "sensitive_fields",
    "within_batch",
]

_SNAPSHOT: str = "_karni_audit_before"
_UID = "karni.audit."

#: Substrings (case-insensitive) that mark a field name as redacted by default.
DEFAULT_REDACT: tuple[str, ...] = ("password", "token", "secret", "key")

#: Never audited even under ``audit = True``: the pk and the timestamps that
#: move on every save.
_ALWAYS_SKIPPED = frozenset({"id", "pk", "created_at", "updated_at"})


_AUDITED: dict[type[models.Model], tuple[str, ...] | None] = {}
_SENSITIVE: dict[type[models.Model], frozenset[str]] = {}

#: The batch (``ChangeBatch`` pk) every entry written in this context joins.
_BATCH: ContextVar[int | None] = ContextVar("karni_audit_batch", default=None)


def current_batch_id() -> int | None:
    """The pk of the batch entries are being written into, or ``None``."""
    return _BATCH.get()


@contextmanager
def within_batch(batch_id: int | None) -> Iterator[None]:
    """Write every entry recorded in the block into the existing batch ``batch_id``.

    What an impersonated session uses: one batch for the whole session,
    re-entered on every request, so every change made while impersonating
    points at the batch that names both people.
    """
    token = _BATCH.set(int(batch_id) if batch_id is not None else None)
    try:
        yield
    finally:
        _BATCH.reset(token)


@contextmanager
def change_batch(kind: str, label: str = "", meta: dict[str, Any] | None = None) -> Iterator[Any]:
    """Group every change recorded inside the block under one ``ChangeBatch``.

    ``with change_batch("import", "orders.xlsx", {"job": str(job.pk)}) as batch:``
    — the batch row is created first (with the current user as actor), each
    entry written while the block runs points at it, and ``batch`` is the row
    (``batch.pk`` is what to store on the operation that owns it). Batches
    nest: the innermost wins.
    """
    from karni.audit.models import ChangeBatch

    user = get_current_user()
    batch = ChangeBatch.objects.create(
        actor_id=getattr(user, "pk", None), kind=kind, label=label[:200], meta=meta or {}
    )
    token = _BATCH.set(int(batch.pk))
    try:
        yield batch
    finally:
        _BATCH.reset(token)


def clear_caches() -> None:
    """Forget the per-model metadata (tests that change ``class Karni`` at runtime)."""
    _AUDITED.clear()
    _SENSITIVE.clear()


def audited_fields(model: type[models.Model]) -> tuple[str, ...] | None:
    """The field names ``Karni.audit`` covers, or ``None`` when the model is not audited."""
    if model in _AUDITED:
        return _AUDITED[model]
    found = _audited_fields(model)
    _AUDITED[model] = found
    return found


def _audited_fields(model: type[models.Model]) -> tuple[str, ...] | None:
    declared = karni_option(model, "audit", False)
    if not declared:
        return None
    names = [field.name for field in model._meta.concrete_fields]
    if declared is True:
        # Generated columns (a SearchField) are derived data, not changes anyone made.
        generated = {f.name for f in model._meta.concrete_fields if getattr(f, "generated", False)}
        return tuple(name for name in names if name not in _ALWAYS_SKIPPED | generated)
    if isinstance(declared, str) or not all(isinstance(name, str) for name in declared):
        raise KarniImproperlyConfigured(
            f"{model.__name__}.Karni.audit must be True or a list of field names.", code="E007"
        )
    unknown = sorted(set(declared) - set(names))
    if unknown:
        raise KarniImproperlyConfigured(
            f"{model.__name__}.Karni.audit names {', '.join(unknown)}, which "
            f"{model.__name__} does not have.",
            code="E007",
        )
    return tuple(dict.fromkeys(declared))


def _redact_patterns() -> tuple[str, ...]:
    configured = getattr(settings, "KARNI_AUDIT_REDACT", None)
    return tuple(configured) if configured is not None else DEFAULT_REDACT


def sensitive_fields(model: type[models.Model]) -> frozenset[str]:
    """Fields recorded as changed, never with their values.

    ``Karni.sensitive`` plus every field whose name contains one of
    ``KARNI_AUDIT_REDACT`` (``password``, ``token``, ``secret``, ``key`` by
    default) — ``api_key`` and ``reset_token`` are redacted without asking.
    """
    if model in _SENSITIVE:
        return _SENSITIVE[model]
    found = _sensitive_fields(model)
    _SENSITIVE[model] = found
    return found


def _sensitive_fields(model: type[models.Model]) -> frozenset[str]:
    declared = karni_option(model, "sensitive", ()) or ()
    if isinstance(declared, str) or not all(isinstance(name, str) for name in declared):
        raise KarniImproperlyConfigured(
            f"{model.__name__}.Karni.sensitive must be a list of field names.", code="E007"
        )
    pattern = re.compile("|".join(re.escape(part) for part in _redact_patterns()), re.I)
    names = {field.name for field in model._meta.concrete_fields}
    found = {name for name in names if pattern.search(name)}
    found.update(name for name in declared if name in names)
    return frozenset(found)


def json_value(value: Any) -> Any:
    """A JSON-safe rendering of a field value (pk for relations, text for the rest)."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, models.Model):
        return json_value(value.pk)
    if isinstance(value, uuid.UUID | decimal.Decimal):
        return str(value)
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return value.total_seconds()
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [json_value(item) for item in value]
    name = getattr(value, "name", None)  # files
    if isinstance(name, str):
        return name
    return str(value)


def _attname(model: type[models.Model], name: str) -> str:
    return str(model._meta.get_field(name).attname)


def snapshot(instance: models.Model, names: tuple[str, ...]) -> dict[str, Any]:
    """The instance's current audited values, JSON-safe, keyed by field name."""
    model = type(instance)
    return {name: json_value(getattr(instance, _attname(model, name), None)) for name in names}


def stored_snapshot(instance: models.Model, names: tuple[str, ...]) -> dict[str, Any] | None:
    """The row as the database holds it now (``None`` when it does not exist)."""
    model = type(instance)
    attnames = [_attname(model, name) for name in names]
    row = model._base_manager.using(instance._state.db).filter(pk=instance.pk).values(*attnames)
    found = row.first()
    if found is None:
        return None
    return {name: json_value(found[attname]) for name, attname in zip(names, attnames, strict=True)}


def diff_values(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any]:
    """``{field: [old, new]}`` for every field whose value differs."""
    names = list(dict.fromkeys([*(before or {}), *(after or {})]))
    found: dict[str, Any] = {}
    for name in names:
        old = (before or {}).get(name)
        new = (after or {}).get(name)
        if old != new:
            found[name] = [old, new]
    return found


def _redact(model: type[models.Model], diff: dict[str, Any]) -> dict[str, Any]:
    sensitive = sensitive_fields(model)
    return {
        name: ([REDACTED, REDACTED] if name in sensitive else change)
        for name, change in diff.items()
    }


def _action(before: dict[str, Any] | None, diff: dict[str, Any], deleted: bool) -> str:
    if deleted:
        return "delete"
    if before is None:
        return "create"
    marker = diff.get("deleted_at")
    if marker is not None:
        old, new = marker
        if old is None and new is not None:
            return "delete"
        if old is not None and new is None:
            return "restore"
    return "update"


def record(instance: models.Model, action: str, diff: dict[str, Any]) -> None:
    """Write (or enqueue) one entry for ``instance``; a no-op when ``diff`` is empty."""
    if not diff:
        return
    model = type(instance)
    user = get_current_user()
    payload = {
        "app_label": model._meta.app_label,
        "model": model._meta.model_name,
        "object_id": str(instance.pk),
        "actor_id": json_value(getattr(user, "pk", None)),
        "action": action,
        "diff": _redact(model, diff),
        "batch_id": _BATCH.get(),
    }
    if getattr(settings, "KARNI_AUDIT_ASYNC", False):
        from karni.audit.tasks import record_change

        transaction.on_commit(lambda: record_change.delay(payload))
        return
    write(payload)


def write(payload: dict[str, Any]) -> None:
    """Insert the entry ``payload`` describes (the synchronous path and the task's body)."""
    from django.contrib.contenttypes.models import ContentType

    from karni.audit.models import ChangeLog

    content_type = ContentType.objects.get_by_natural_key(payload["app_label"], payload["model"])
    ChangeLog.objects.create(
        content_type=content_type,
        object_id=payload["object_id"],
        actor_id=payload.get("actor_id"),
        action=payload["action"],
        diff=payload["diff"],
        batch_id=payload.get("batch_id"),
    )


# receivers


def _pre_save(sender: type[models.Model], instance: models.Model, raw: bool, **kwargs: Any) -> None:
    names = audited_fields(sender)
    if names is None or raw:
        return
    before = None
    if not instance._state.adding and instance.pk is not None:
        before = stored_snapshot(instance, names)
    setattr(instance, _SNAPSHOT, before)


def _post_save(
    sender: type[models.Model], instance: models.Model, created: bool, raw: bool, **kwargs: Any
) -> None:
    names = audited_fields(sender)
    if names is None or raw:
        return
    before = getattr(instance, _SNAPSHOT, None)
    if hasattr(instance, _SNAPSHOT):
        delattr(instance, _SNAPSHOT)
    after = snapshot(instance, names)
    if created or before is None:
        diff = {name: [None, value] for name, value in after.items() if value not in (None, "")}
        record(instance, "create", diff)
        return
    diff = diff_values(before, after)
    record(instance, _action(before, diff, deleted=False), diff)


def _post_delete(sender: type[models.Model], instance: models.Model, **kwargs: Any) -> None:
    names = audited_fields(sender)
    if names is None:
        return
    before = snapshot(instance, names)
    diff = {name: [value, None] for name, value in before.items() if value not in (None, "")}
    record(instance, "delete", diff or {"pk": [json_value(instance.pk), None]})


def connect() -> None:
    """Connect the receivers (idempotent through ``dispatch_uid``)."""
    pre_save.connect(_pre_save, dispatch_uid=_UID + "pre_save", weak=False)
    post_save.connect(_post_save, dispatch_uid=_UID + "post_save", weak=False)
    post_delete.connect(_post_delete, dispatch_uid=_UID + "post_delete", weak=False)
