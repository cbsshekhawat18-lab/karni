"""Propose, decide, apply, sweep — the module's whole behaviour, callable from anywhere.

Every rule the brief names is enforced here, not in a view: the maker is
never the checker (:func:`decide` refuses it whoever calls it), a checker
needs the approve permission and the model's approver role, and sees only
pending changes whose row lies inside their own scope (:func:`visible_to`).
"""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Model, Q, QuerySet
from django.utils import timezone
from karni.accounts.permissions import has_role
from karni.accounts.roles import rows_for, user_can
from karni.audit.capture import json_value
from karni.exceptions import KarniValueError
from karni.middleware import current_user
from karni.rows import apply_rows

from karni_approvals.interception import applying
from karni_approvals.meta import ApprovalPolicy, approval_policy
from karni_approvals.models import Decision, PendingChange

__all__ = [
    "APPROVE_PERMISSION",
    "ApprovalError",
    "apply",
    "decide",
    "may_decide",
    "payload",
    "pending_count",
    "propose",
    "sweep",
    "visible_to",
]

logger = logging.getLogger(__name__)

APPROVE_PERMISSION = "karni_approvals.pendingchange:approve"
REJECT_PERMISSION = "karni_approvals.pendingchange:reject"


class ApprovalError(KarniValueError):
    """A decision the rules refuse; ``code`` says which rule (APR002–APR006)."""


def propose(
    instance: Model,
    action: str,
    changes: dict[str, Any],
    maker: Any,
    *,
    policy: ApprovalPolicy | None = None,
) -> PendingChange:
    """Record ``changes`` to ``instance`` as a pending change by ``maker`` and notify checkers."""
    model = type(instance)
    policy = policy if policy is not None else approval_policy(model)
    if policy is None:
        raise ApprovalError(f"{model.__name__} declares no requires_approval.", code="APR007")
    now = timezone.now()
    with transaction.atomic():
        pending = PendingChange.objects.create(
            content_type=ContentType.objects.get_for_model(model),
            object_id="" if action == "create" else str(instance.pk),
            action=action,
            summary=str(instance)[:200] if action != "create" else _create_summary(instance),
            changes=changes,
            maker=maker if getattr(maker, "is_authenticated", False) else None,
            required=policy.approvals,
            expires_at=now + policy.timeout if policy.timeout is not None else None,
        )
    from karni_approvals.tasks import notify_checkers

    pending_id = str(pending.pk)
    transaction.on_commit(lambda: notify_checkers.delay(pending_id))
    return pending


def _create_summary(instance: Model) -> str:
    try:
        text = str(instance)
    except Exception:  # noqa: BLE001 - __str__ may need a saved row
        text = ""
    verbose = str(type(instance)._meta.verbose_name)
    return (
        f"new {verbose}: {text}"
        if text and text != f"{verbose} object (None)"
        else f"new {verbose}"
    )[:200]


def payload(pending: PendingChange) -> dict[str, Any]:
    """The pending change as the API renders it (what a 202 carries)."""
    from karni_approvals.api import PendingChangeSerializer

    data: dict[str, Any] = dict(PendingChangeSerializer(pending).data)
    return data


# who may decide, and what they see


def _target_rows(user: Any, model: type[Model]) -> Any:
    return rows_for(user, model, "view")


def visible_to(user: Any, queryset: QuerySet[PendingChange]) -> QuerySet[PendingChange]:
    """``queryset`` narrowed to the pending changes whose row ``user`` may view.

    A create has no row yet: it is visible only to a user who may view every
    row of that model. A superuser sees everything.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return queryset.none()
    if getattr(user, "is_superuser", False):
        return queryset
    condition = Q(pk__in=[])
    content_types = ContentType.objects.filter(
        pk__in=queryset.values_list("content_type_id", flat=True).distinct()
    )
    for content_type in content_types:
        model = content_type.model_class()
        if model is None:
            continue
        rows = _target_rows(user, model)
        if rows is True:
            condition |= Q(content_type=content_type)
        elif rows is not False:
            readable = apply_rows(model._default_manager.all(), rows).values_list("pk", flat=True)
            condition |= Q(content_type=content_type, object_id__in=[str(pk) for pk in readable])
    return queryset.filter(condition)


def may_decide(user: Any, pending: PendingChange, verdict: str = "approve") -> tuple[bool, str]:
    """``(allowed, why not)`` for ``user`` deciding ``pending`` — every rule, in order."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False, "sign in to decide."
    if pending.maker_id is not None and pending.maker_id == user.pk:
        return False, "the maker cannot be the checker."
    permission = APPROVE_PERMISSION if verdict == "approve" else REJECT_PERMISSION
    if not user_can(user, permission):
        return False, f"you do not hold {permission}."
    model = pending.model_class
    policy = approval_policy(model) if model is not None else None
    if policy is not None and policy.roles and not has_role(user, *policy.roles):
        name = getattr(model, "__name__", "these")
        return False, f"only roles {', '.join(policy.roles)} may decide {name} changes."
    if not visible_to(user, PendingChange.objects.filter(pk=pending.pk)).exists():
        return False, "this change is outside your scope."
    return True, ""


def decide(pending: PendingChange, checker: Any, verdict: str, reason: str = "") -> PendingChange:
    """Record ``checker``'s verdict; apply the change once enough approvals are in.

    Raises :class:`ApprovalError`: ``APR002`` (maker is the checker),
    ``APR003`` (not allowed, or outside the checker's scope), ``APR004``
    (this checker already decided), ``APR005`` (not pending any more),
    ``APR006`` (the row changed since, so the change could not be applied —
    the decision stands and the change is marked ``failed``).
    """
    if verdict not in (Decision.Verdict.APPROVE, Decision.Verdict.REJECT):
        raise ApprovalError(f"verdict must be approve or reject, not {verdict!r}.", code="APR003")
    failure: ApprovalError | None = None
    with transaction.atomic():
        locked = PendingChange.objects.select_for_update().get(pk=pending.pk)
        if not locked.is_pending:
            raise ApprovalError(f"this change is already {locked.status}.", code="APR005")
        if locked.maker_id is not None and locked.maker_id == getattr(checker, "pk", None):
            raise ApprovalError("the maker cannot be the checker.", code="APR002")
        allowed, why = may_decide(checker, locked, verdict)
        if not allowed:
            raise ApprovalError(why, code="APR003")
        now = timezone.now()
        with current_user(checker):
            try:
                with transaction.atomic():
                    Decision.objects.create(
                        pending=locked, checker=checker, verdict=verdict, reason=reason or ""
                    )
            except IntegrityError as exc:
                raise ApprovalError("you have already decided this change.", code="APR004") from exc
            if verdict == Decision.Verdict.REJECT:
                locked.status = PendingChange.Status.REJECTED
                locked.resolved_at, locked.resolved_by, locked.reason = now, checker, reason or ""
                locked.save(
                    update_fields=["status", "resolved_at", "resolved_by", "reason", "updated_at"]
                )
            else:
                locked.approvals += 1
                fields = ["approvals", "updated_at"]
                if locked.approvals >= locked.required:
                    try:
                        with transaction.atomic():
                            apply(locked, checker)
                    except ApprovalError as exc:
                        failure = exc
                    except (IntegrityError, DjangoValidationError) as exc:
                        failure = ApprovalError(
                            f"the change could not be applied: {exc}", code="APR006"
                        )
                    locked.status = (
                        PendingChange.Status.FAILED
                        if failure is not None
                        else PendingChange.Status.APPROVED
                    )
                    locked.resolved_at, locked.resolved_by = now, checker
                    locked.reason = str(failure) if failure is not None else (reason or "")
                    fields += ["status", "resolved_at", "resolved_by", "reason"]
                locked.save(update_fields=fields)
    pending.refresh_from_db()
    if failure is not None:
        raise failure
    return pending


def _assign(obj: Model, name: str, value: Any) -> None:
    field = obj._meta.get_field(name)
    if getattr(field, "is_relation", False) and getattr(field, "attname", None):
        setattr(obj, field.attname, value)
    else:
        setattr(obj, name, value)


def apply(pending: PendingChange, by: Any) -> Model | None:
    """Write the change ``pending`` holds, as ``by`` — the row's own history records it.

    Each recorded old value must still be the row's current value; otherwise
    the change is stale (``APR006``) and nothing is written.
    """
    model = pending.model_class
    if model is None:
        raise ApprovalError("the model this change targets no longer exists.", code="APR006")
    changes: dict[str, Any] = dict(pending.changes or {})
    with applying(), current_user(by):
        if pending.action == PendingChange.Action.CREATE:
            obj = model()
            for name, (_old, new) in changes.items():
                _assign(obj, name, new)
            obj.save()
            return obj
        obj = model._base_manager.filter(pk=pending.object_id).first()
        if obj is None:
            raise ApprovalError("the row no longer exists.", code="APR006")
        if pending.action == PendingChange.Action.DELETE:
            obj.delete()
            return obj
        stale = []
        for name, (old, _new) in changes.items():
            field = obj._meta.get_field(name)
            current = json_value(getattr(obj, getattr(field, "attname", name)))
            if current != old:
                stale.append(name)
        if stale:
            raise ApprovalError(
                f"the row changed since this was proposed ({', '.join(stale)}); propose it again.",
                code="APR006",
            )
        for name, (_old, new) in changes.items():
            _assign(obj, name, new)
        obj.save()
        return obj


def pending_count(user: Any) -> int:
    """How many pending changes ``user`` may decide — the badge."""
    queryset = visible_to(user, PendingChange.objects.filter(status=PendingChange.Status.PENDING))
    if user is not None and getattr(user, "is_authenticated", False):
        queryset = queryset.exclude(maker_id=user.pk)
    return queryset.count()


def sweep(now: Any = None) -> dict[str, int]:
    """Expire or escalate every pending change past its deadline (the hourly task)."""
    from karni_approvals.tasks import notify_escalation

    now = now or timezone.now()
    counts = {"expired": 0, "escalated": 0}
    due = PendingChange.objects.filter(status=PendingChange.Status.PENDING, expires_at__lte=now)
    for pending in due.select_related("content_type"):
        model = pending.model_class
        policy = approval_policy(model) if model is not None else None
        if policy is not None and policy.on_timeout == "escalate" and policy.timeout is not None:
            pending.escalated_at = now
            pending.expires_at = now + policy.timeout
            pending.save(update_fields=["escalated_at", "expires_at", "updated_at"])
            transaction.on_commit(lambda pk=str(pending.pk): notify_escalation.delay(pk))
            counts["escalated"] += 1
        else:
            pending.status = PendingChange.Status.EXPIRED
            pending.resolved_at = now
            pending.reason = "timed out"
            pending.save(update_fields=["status", "resolved_at", "reason", "updated_at"])
            counts["expired"] += 1
    return counts
