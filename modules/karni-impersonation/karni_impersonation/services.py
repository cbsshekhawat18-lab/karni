"""Start, stop, resolve and police an impersonated session — the whole behaviour, in code.

Every rule the brief names lives here, not in a view: the explicit
permission, the no-escalation comparison, the reason, the time limit, the
blocked list. The middleware, the API, the admin page and the veto call
these functions.
"""

from __future__ import annotations

import fnmatch
import logging
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from karni.accounts.roles import grants_for, user_can
from karni.audit.capture import change_batch, within_batch
from karni.exceptions import KarniValueError
from karni.middleware import current_user

from karni_impersonation import conf
from karni_impersonation.models import ImpersonationSession

__all__ = [
    "EXPIRED",
    "LOGOUT",
    "PERMISSION",
    "STOPPED",
    "SWEPT",
    "SESSION_KEY",
    "ImpersonationError",
    "active_session",
    "attach",
    "can_impersonate",
    "current",
    "detach",
    "end_on_logout",
    "impersonating",
    "is_blocked",
    "is_blocked_path",
    "privilege_gap",
    "start",
    "stop",
    "sweep",
]

logger = logging.getLogger(__name__)

PERMISSION = "karni_impersonation.impersonationsession:impersonate"
#: ``ImpersonationSession.end_reason`` values (``ImpersonationSession.EndReason`` labels them).
STOPPED = "stopped"
EXPIRED = "expired"
LOGOUT = "logout"
SWEPT = "swept"
#: The Django session key carrying the active impersonation (session auth mode).
SESSION_KEY = "karni_impersonation"

_CURRENT: ContextVar[ImpersonationSession | None] = ContextVar("karni_impersonation", default=None)


class ImpersonationError(KarniValueError):
    """A start or stop the rules refuse; ``code`` says which rule (IMP001–IMP005)."""


# who may impersonate whom


def _value(scope: str, path: str) -> str:
    return f"{scope}:{path}" if path else scope


def privilege_gap(actor: Any, target: Any) -> str | None:
    """What ``target`` holds that ``actor`` does not — ``None`` when nothing (no escalation)."""
    if getattr(target, "is_superuser", False) and not getattr(actor, "is_superuser", False):
        return "the target is a superuser"
    if getattr(target, "is_staff", False) and not getattr(actor, "is_staff", False):
        return "the target is staff"
    if getattr(actor, "is_superuser", False):
        return None
    mine = grants_for(actor)
    for key, grants in grants_for(target).items():
        held = mine.get(key, [])
        for grant in grants:
            covered = any(
                h.scope == "all" or (h.scope, h.scope_path) == (grant.scope, grant.scope_path)
                for h in held
            )
            if not covered:
                return f"the target holds {key} ({_value(grant.scope, grant.scope_path)})"
    extra = sorted(set(target.get_all_permissions()) - set(actor.get_all_permissions()))
    if extra:
        return f"the target holds the Django permission {extra[0]}"
    return None


def can_impersonate(actor: Any, target: Any) -> tuple[bool, str]:
    """``(allowed, why not)`` — the explicit permission first, then no escalation."""
    if actor is None or not getattr(actor, "is_authenticated", False):
        return False, "sign in first."
    if not getattr(actor, "is_active", True):
        return False, "your account is inactive."
    if not user_can(actor, PERMISSION):
        return False, f"you do not hold {PERMISSION}."
    if target is None or target.pk == actor.pk:
        return False, "you cannot impersonate yourself."
    if not getattr(target, "is_active", True):
        return False, "the target account is inactive."
    gap = privilege_gap(actor, target)
    if gap is not None:
        return False, f"{gap}, which you do not: impersonation never escalates privileges."
    return True, ""


# the session


def start(actor: Any, target: Any, reason: str = "", request: Any = None) -> ImpersonationSession:
    """Begin acting as ``target``: the record, its audit batch, the target's notification.

    Raises :class:`ImpersonationError`: ``IMP001`` (no permission), ``IMP002``
    (privilege escalation), ``IMP003`` (reason required), ``IMP004`` (self or
    inactive).
    """
    if (
        actor is None
        or not getattr(actor, "is_authenticated", False)
        or not user_can(actor, PERMISSION)
    ):
        raise ImpersonationError(f"you do not hold {PERMISSION}.", code="IMP001")
    if target is None or target.pk == actor.pk or not getattr(target, "is_active", True):
        raise ImpersonationError(
            "you cannot impersonate yourself or an inactive account.", code="IMP004"
        )
    gap = privilege_gap(actor, target)
    if gap is not None:
        raise ImpersonationError(
            f"{gap}, which you do not: impersonation never escalates privileges.", code="IMP002"
        )
    reason = (reason or "").strip()
    if conf.get("KARNI_IMPERSONATION_REQUIRE_REASON") and not reason:
        raise ImpersonationError("a reason is required to impersonate someone.", code="IMP003")
    minutes = int(conf.get("KARNI_IMPERSONATION_MAX_MINUTES") or 60)
    now = timezone.now()
    meta = {"target": str(target.pk), "target_email": _email(target), "reason": reason}
    with transaction.atomic(), current_user(actor):
        with change_batch(
            "impersonation", f"{_email(actor)} as {_email(target)}"[:200], meta
        ) as batch:
            session = ImpersonationSession.objects.create(
                actor=actor,
                target=target,
                reason=reason,
                started_at=now,
                expires_at=now + timedelta(minutes=max(minutes, 1)),
                ip=_ip(request),
                user_agent=str(getattr(request, "META", {}).get("HTTP_USER_AGENT", ""))[:255]
                if request is not None
                else "",
                batch_id=int(batch.pk),
            )
    if conf.get("KARNI_IMPERSONATION_NOTIFY_TARGET"):
        from karni_impersonation.tasks import notify_target

        session_id = str(session.pk)
        transaction.on_commit(lambda: notify_target.delay(session_id))
    logger.info(
        "karni_impersonation: %s started acting as %s (%s)", _email(actor), _email(target), reason
    )
    return session


def stop(session: ImpersonationSession, reason: str = STOPPED) -> ImpersonationSession:
    """End the session now (idempotent); the record keeps when and why."""
    if session.ended_at is not None:
        return session
    with current_user(session.actor):
        session.ended_at = timezone.now()
        session.end_reason = reason
        session.save(update_fields=["ended_at", "end_reason", "updated_at"])
    logger.info("karni_impersonation: session %s ended (%s)", session.pk, reason)
    return session


def active_session(session_id: Any) -> ImpersonationSession | None:
    """The live session with this id, or ``None`` — an expired one is ended on the way."""
    if not session_id:
        return None
    try:
        session = (
            ImpersonationSession.objects.filter(pk=session_id)
            .select_related("actor", "target")
            .first()
        )
    except (ValueError, TypeError):
        return None
    if session is None or session.ended_at is not None:
        return None
    if session.is_expired:
        stop(session, EXPIRED)
        return None
    return session


def sweep(now: Any = None) -> int:
    """End every session past its limit that nothing ended (the hourly task)."""
    now = now or timezone.now()
    count = 0
    for session in ImpersonationSession.objects.filter(ended_at__isnull=True, expires_at__lte=now):
        stop(session, SWEPT)
        count += 1
    return count


# the request context


@contextmanager
def impersonating(session: ImpersonationSession | None) -> Iterator[None]:
    """Mark the running code as this session: the veto sees it, the audit batch joins it."""
    token = _CURRENT.set(session)
    try:
        with within_batch(session.batch_id if session is not None else None):
            yield
    finally:
        _CURRENT.reset(token)


def current() -> ImpersonationSession | None:
    """The impersonated session the running request belongs to, or ``None``."""
    return _CURRENT.get()


def attach(request: Any, session: ImpersonationSession) -> None:
    """Session auth mode: remember the session in the Django session."""
    django_session = getattr(request, "session", None)
    if django_session is not None:
        django_session[SESSION_KEY] = str(session.pk)


def detach(request: Any) -> None:
    django_session = getattr(request, "session", None)
    if django_session is not None:
        django_session.pop(SESSION_KEY, None)


def end_on_logout(sender: Any, request: Any, user: Any, **kwargs: Any) -> None:
    """``user_logged_out`` receiver: an impersonator who logs out ends the session."""
    django_session = getattr(request, "session", None)
    if django_session is None:
        return
    session_id = django_session.pop(SESSION_KEY, None)
    if not session_id:
        return
    session = ImpersonationSession.objects.filter(pk=session_id, ended_at__isnull=True).first()
    if session is not None:
        stop(session, LOGOUT)


# the blocked list


def _patterns() -> list[str]:
    configured = conf.get("KARNI_IMPERSONATION_BLOCKED") or []
    return [str(pattern) for pattern in configured]


def is_blocked(names: Iterable[str]) -> str | None:
    """The first blocked pattern matching any of ``names`` (action, permission, model)."""
    candidates = [name for name in names if name]
    for pattern in _patterns():
        if pattern.startswith("/"):
            continue
        for name in candidates:
            if fnmatch.fnmatchcase(name, pattern):
                return pattern
    return None


def is_blocked_path(path: str) -> str | None:
    """The blocked path pattern ``path`` matches, or ``None``."""
    for pattern in _patterns():
        if pattern.startswith("/") and fnmatch.fnmatchcase(path, pattern):
            return pattern
    return None


# helpers


def _email(user: Any) -> str:
    return str(getattr(user, "email", "") or user.get_username())


def _ip(request: Any) -> str:
    if request is None:
        return ""
    meta = getattr(request, "META", {})
    forwarded = str(meta.get("HTTP_X_FORWARDED_FOR", ""))
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return str(meta.get("REMOTE_ADDR", ""))[:64]


def find_user(query: str) -> Any | None:
    """A user by email (case-insensitive) or primary key."""
    model = get_user_model()
    manager = model._default_manager
    found = manager.filter(**{f"{model.USERNAME_FIELD}__iexact": query}).first()
    if found is not None:
        return found
    try:
        return manager.filter(pk=query).first()
    except (ValueError, TypeError):
        return None
    except Exception as exc:  # noqa: BLE001 - an invalid UUID raises ValidationError
        if type(exc).__name__ == "ValidationError":
            return None
        raise
