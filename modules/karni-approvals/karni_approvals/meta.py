"""The approval policy a model declares in ``class Karni``, read in one place.

::

    class Invoice(BaseModel):
        class Karni:
            requires_approval = ["amount", "status"]   # or True: any change, create and delete too
            approvals_required = 2                      # default KARNI_APPROVALS_REQUIRED
            approver_roles = ["finance"]                # default KARNI_APPROVALS_APPROVER_ROLES
            approval_timeout = timedelta(hours=48)      # or hours as an int; default the setting
            approval_on_timeout = "escalate"            # or "expire"
            approval_escalation_roles = ["cfo"]

Every option has a project-wide default in :mod:`karni_approvals.conf`;
a model without ``requires_approval`` has no policy and is never held.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.core.exceptions import FieldDoesNotExist
from django.db import models
from karni.exceptions import KarniImproperlyConfigured
from karni.meta import Option, karni_option

from karni_approvals import conf

__all__ = ["KARNI_OPTIONS", "ApprovalPolicy", "approval_policy", "clear_caches"]

ON_TIMEOUT = ("expire", "escalate")

#: The ``class Karni`` keys this module reads (listed in docs/REFERENCE.md).
KARNI_OPTIONS: tuple[Option, ...] = (
    Option(
        "requires_approval",
        "unset: never held",
        "Hold changes for a second person's approval: a list of guarded fields, or `True` "
        "for any change, create and delete included.",
        'requires_approval = ["amount", "status"]',
    ),
    Option(
        "approvals_required",
        "`KARNI_APPROVALS_REQUIRED` (1)",
        "Approvals a pending change needs before it is applied.",
        "approvals_required = 2",
    ),
    Option(
        "approver_roles",
        "`KARNI_APPROVALS_APPROVER_ROLES`",
        "Roles that may approve, on top of holding the approve permission.",
        'approver_roles = ["finance"]',
    ),
    Option(
        "approval_timeout",
        "`KARNI_APPROVALS_TIMEOUT_HOURS` (0: never)",
        "How long a change may wait: a `timedelta`, or hours as an integer.",
        "approval_timeout = timedelta(hours=48)",
    ),
    Option(
        "approval_on_timeout",
        "`KARNI_APPROVALS_ON_TIMEOUT` (`expire`)",
        "What a timeout does: `expire` the change, or `escalate` it to the escalation roles.",
        'approval_on_timeout = "escalate"',
    ),
    Option(
        "approval_escalation_roles",
        "`KARNI_APPROVALS_ESCALATION_ROLES`",
        "Roles notified when a change escalates.",
        'approval_escalation_roles = ["cfo"]',
    ),
)


@dataclass(frozen=True)
class ApprovalPolicy:
    """What a model's ``class Karni`` says about approvals."""

    fields: tuple[str, ...] | None
    """The guarded fields. ``None`` means any change, including create and delete."""

    approvals: int
    roles: tuple[str, ...]
    timeout: timedelta | None
    on_timeout: str
    escalation_roles: tuple[str, ...]

    @property
    def any_change(self) -> bool:
        return self.fields is None


_CACHE: dict[type[models.Model], ApprovalPolicy | None] = {}


def clear_caches() -> None:
    """Forget the per-model policies (tests that change ``class Karni`` at runtime)."""
    _CACHE.clear()


def _bad(model: type[models.Model], message: str) -> KarniImproperlyConfigured:
    return KarniImproperlyConfigured(f"{model.__name__}.Karni: {message}", code="APR007")


def _roles(model: type[models.Model], name: str, default: Any) -> tuple[str, ...]:
    value = karni_option(model, name, None)
    if value is None:
        value = default
    if isinstance(value, str) or not all(isinstance(slug, str) and slug for slug in value):
        raise _bad(model, f"{name} must be a list of role slugs.")
    return tuple(dict.fromkeys(value))


def _timeout(model: type[models.Model]) -> timedelta | None:
    value = karni_option(model, "approval_timeout", None)
    if value is None:
        hours = int(conf.get("KARNI_APPROVALS_TIMEOUT_HOURS") or 0)
        return timedelta(hours=hours) if hours > 0 else None
    if isinstance(value, timedelta):
        return value if value > timedelta(0) else None
    if isinstance(value, int | float) and not isinstance(value, bool):
        return timedelta(hours=float(value)) if value > 0 else None
    raise _bad(model, "approval_timeout must be a timedelta or a number of hours.")


def approval_policy(model: type[models.Model]) -> ApprovalPolicy | None:
    """The model's policy, or ``None`` when it declares no ``requires_approval``."""
    if model in _CACHE:
        return _CACHE[model]
    policy = _approval_policy(model)
    _CACHE[model] = policy
    return policy


def _approval_policy(model: type[models.Model]) -> ApprovalPolicy | None:
    declared = karni_option(model, "requires_approval", None)
    if not declared:
        return None
    fields: tuple[str, ...] | None
    if declared is True:
        fields = None
    else:
        if isinstance(declared, str) or not all(isinstance(name, str) for name in declared):
            raise _bad(model, "requires_approval must be True or a list of field names.")
        for name in declared:
            try:
                model._meta.get_field(name)
            except FieldDoesNotExist as exc:
                raise _bad(
                    model, f"requires_approval names {name!r}, which is not a field."
                ) from exc
        fields = tuple(dict.fromkeys(declared))
        if not fields:
            return None
    approvals = karni_option(model, "approvals_required", None)
    if approvals is None:
        approvals = conf.get("KARNI_APPROVALS_REQUIRED")
    if isinstance(approvals, bool) or not isinstance(approvals, int) or approvals < 1:
        raise _bad(model, "approvals_required must be a positive integer.")
    on_timeout = str(
        karni_option(model, "approval_on_timeout", None) or conf.get("KARNI_APPROVALS_ON_TIMEOUT")
    )
    if on_timeout not in ON_TIMEOUT:
        raise _bad(model, f"approval_on_timeout must be one of {', '.join(ON_TIMEOUT)}.")
    return ApprovalPolicy(
        fields=fields,
        approvals=approvals,
        roles=_roles(model, "approver_roles", conf.get("KARNI_APPROVALS_APPROVER_ROLES")),
        timeout=_timeout(model),
        on_timeout=on_timeout,
        escalation_roles=_roles(
            model, "approval_escalation_roles", conf.get("KARNI_APPROVALS_ESCALATION_ROLES")
        ),
    )
