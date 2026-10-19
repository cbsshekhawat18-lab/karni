"""Turn a maker's guarded write into a pending change — before any SQL runs.

Connected to :data:`karni.signals.pre_write` (every ``BaseModel`` save and
delete). For a model with a policy, when the current user is a person and
the change touches a guarded field, a :class:`PendingChange` is created and
:class:`karni.exceptions.KarniWriteDeferred` stops the write: the API
answers 202 with the pending change, the admin shows the message, plain
code gets the exception.

Writes pass through unchanged when there is no current user (migrations,
seeds, management commands, Celery tasks that set none), inside
:func:`applying` (the module applying an approved change) and inside
:func:`bypass` (trusted code that says why).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from django.db import models
from karni.audit.capture import diff_values, json_value, snapshot, stored_snapshot
from karni.exceptions import KarniValueError, KarniWriteDeferred
from karni.middleware import get_current_user
from karni.signals import pre_write

from karni_approvals.meta import ApprovalPolicy, approval_policy

__all__ = ["applying", "bypass", "connect", "guarded_diff", "is_applying"]

_APPLYING: ContextVar[bool] = ContextVar("karni_approvals_applying", default=False)
_BYPASS: ContextVar[str | None] = ContextVar("karni_approvals_bypass", default=None)
_UID = "karni_approvals.pre_write"

#: Never part of a diff: the pk and what every save moves anyway.
_SKIPPED = frozenset({"id", "pk", "created_at", "updated_at", "created_by", "updated_by"})


@contextmanager
def applying() -> Iterator[None]:
    """The module applying an approved change: the interceptor stands aside."""
    token = _APPLYING.set(True)
    try:
        yield
    finally:
        _APPLYING.reset(token)


@contextmanager
def bypass(reason: str) -> Iterator[None]:
    """Trusted code writing guarded rows directly; ``reason`` is required and greppable."""
    if not reason or not reason.strip():
        raise KarniValueError(
            "bypass(reason=...) needs a reason saying why approvals are skipped.", code="APR007"
        )
    token = _BYPASS.set(reason)
    try:
        yield
    finally:
        _BYPASS.reset(token)


def is_applying() -> bool:
    return _APPLYING.get()


def _names(model: type[models.Model], update_fields: Any) -> tuple[str, ...]:
    names = [f.name for f in model._meta.concrete_fields if f.name not in _SKIPPED]
    if update_fields:
        wanted = set(update_fields)
        names = [name for name in names if name in wanted]
    return tuple(names)


def guarded_diff(
    instance: models.Model, action: str, policy: ApprovalPolicy, update_fields: Any = None
) -> dict[str, Any] | None:
    """The change as ``{field: [old, new]}`` when the policy holds it, else ``None``.

    A whole change is held when any guarded field is in it — half a write
    would be a different change. A create under a field list is held only
    when a guarded field differs from its default; a delete only under
    ``requires_approval = True``.
    """
    model = type(instance)
    if action == "delete":
        return {} if policy.any_change else None
    names = _names(model, update_fields)
    after = snapshot(instance, names)
    if action == "create":
        diff = {name: [None, value] for name, value in after.items() if value not in (None, "")}
        if policy.any_change:
            return diff
        for name in policy.fields or ():
            field = model._meta.get_field(name)
            default = json_value(field.get_default()) if field.has_default() else None
            if name in after and after[name] not in (None, "") and after[name] != default:
                return diff
        return None
    before = stored_snapshot(instance, names)
    if before is None:
        return None  # the row is gone; let the save fail on its own terms
    diff = diff_values(before, after)
    if not diff:
        return None
    if policy.any_change or any(name in diff for name in policy.fields or ()):
        return diff
    return None


def _on_pre_write(
    sender: type[models.Model],
    instance: models.Model,
    action: str,
    update_fields: Any,
    **kwargs: Any,
) -> None:
    policy = approval_policy(sender)
    if policy is None or _APPLYING.get() or _BYPASS.get() is not None:
        return
    maker = get_current_user()
    if maker is None:
        return  # unattended code: migrations, seeds, commands
    diff = guarded_diff(instance, action, policy, update_fields)
    if diff is None:
        return
    from karni_approvals import services

    pending = services.propose(instance, action, diff, maker, policy=policy)
    needed = pending.required
    raise KarniWriteDeferred(
        f"{pending.summary or sender._meta.verbose_name} was sent for approval "
        f"({needed} approval{'s' if needed != 1 else ''} needed).",
        code="APR001",
        payload=services.payload(pending),
        status=202,
    )


def connect() -> None:
    """Connect the interceptor (idempotent through ``dispatch_uid``)."""
    pre_write.connect(_on_pre_write, dispatch_uid=_UID, weak=False)
