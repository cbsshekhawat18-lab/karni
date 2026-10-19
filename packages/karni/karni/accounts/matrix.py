"""The permission matrix (ADR 0002, P5): grants as a screen and an API, with guard rails.

Roles across, models down, one scope selector per action — the screen that
lets a non-developer change who may do what, with no deploy. Everything here
is plain data in and out, so the admin page (:mod:`karni.accounts.matrix_admin`)
and the API (:mod:`karni.accounts.api.matrix`) are two thin renderings of the
same four functions:

* :func:`build_matrix` — every role × ``app.model:action`` cell with its
  scope, where it came from (``declared`` by ``KARNI_ROLES`` or set in the
  ``matrix``), what the declaration says, and whether it is locked;
* :func:`plan_changes` — the diff a set of requested cells would make, with
  every change the guard rails refuse and why (the confirmation step);
* :func:`apply_changes` — the same, written atomically or not at all, each
  row change recorded by ``karni.audit`` with the operator as the actor;
* :func:`effective_permissions` — what one user may do and WHY: which role
  granted it, at which scope, declared or set here.

The guard rails, all in :func:`plan_changes`:

1. a system role cannot lose a declared grant — its ``KARNI_ROLES`` cells
   are locked here; change the declaration instead;
2. nobody grants what they do not hold: touching ``app.model:action`` needs
   the operator to hold that permission, and granting a scope needs the
   operator to hold it at that scope (``all`` covers everything);
3. nobody removes their own last permission to change permissions
   (``karni_accounts.rolepermission:change``, :data:`MATRIX_PERMISSION``);
4. the diff is shown before it is saved (the admin's confirmation page,
   ``dry_run`` on the API).

How the matrix and the declaration share the tables: a grant the matrix
sets carries ``origin = "matrix"`` and ``karni sync-roles`` leaves it alone
(reported as overridden); a declared grant the matrix revokes stays as a row
with scope ``none`` so the next sync does not quietly restore it; a cell set
back to the declared value is handed back to the declaration. Nothing here
touches ``auth.Permission``.

Override / escape hatch: ``KARNI_MATRIX_EXCLUDE`` hides apps or models from
the matrix (framework internals by default); every function takes the
operator explicitly, so a project's own UI or fixtures call them directly.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Final

from django.apps import apps
from django.conf import settings
from django.db import models, transaction

from karni.accounts.roles import (
    NONE_SCOPE,
    Grant,
    custom_scopes,
    declared_roles,
    expand_grants,
    grants_for,
    permission_keys,
)
from karni.exceptions import KarniValueError
from karni.meta import model_actions, owner_field, scope_paths
from karni.middleware import current_user

__all__ = [
    "DECLARED",
    "DEFAULT_MATRIX_EXCLUDE",
    "MATRIX_PERMISSION",
    "Cell",
    "Change",
    "Effective",
    "EffectiveReport",
    "Matrix",
    "MatrixModel",
    "MatrixRefused",
    "MatrixRole",
    "Plan",
    "Refusal",
    "Source",
    "apply_changes",
    "build_matrix",
    "effective_permissions",
    "matrix_models",
    "plan_changes",
    "recent_changes",
    "scope_options",
    "scope_value",
]

#: The permission the matrix is gated on: ``:view`` to look, ``:change`` to edit.
MATRIX_PERMISSION: Final = "karni_accounts.rolepermission"

#: A requested cell value meaning "whatever ``KARNI_ROLES`` declares".
DECLARED: Final = "declared"

#: Fallback for ``KARNI_MATRIX_EXCLUDE`` (kept in sync with ``karni.conf.base``):
#: framework internals nobody grants by role.
DEFAULT_MATRIX_EXCLUDE: tuple[str, ...] = (
    "admin",
    "auth",
    "contenttypes",
    "sessions",
    "sites",
    "django_celery_beat",
    "django_celery_results",
    "token_blacklist",
    "django_otp",
    "otp_totp",
    "otp_static",
    "account",
    "socialaccount",
    "karni_audit",
    "karni_accounts.OneTimeToken",
    "karni_accounts.Permission",
)

_ORIGIN_DECLARED: Final = "declared"
_ORIGIN_MATRIX: Final = "matrix"


# the matrix


@dataclass(frozen=True)
class MatrixRole:
    """One column: a role, flagged when the project's declaration owns it."""

    slug: str
    name: str
    is_system: bool
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "system": self.is_system,
            "description": self.description,
        }


@dataclass(frozen=True)
class MatrixModel:
    """One row group: a model, its actions and the scopes its grants may take."""

    label: str
    name: str
    app: str
    actions: tuple[str, ...]
    scopes: tuple[tuple[str, str], ...]

    def permission(self, action: str) -> str:
        return f"{self.label}:{action}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "name": self.name,
            "app": self.app,
            "actions": list(self.actions),
            "scopes": [{"value": value, "label": label} for value, label in self.scopes],
        }


@dataclass(frozen=True)
class Cell:
    """One role × permission: its scope (``None`` = no grant), origin and declaration."""

    role: str
    permission: str
    scope: str | None
    origin: str | None
    declared: str | None
    locked: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "origin": self.origin,
            "declared": self.declared,
            "locked": self.locked,
        }


@dataclass
class Matrix:
    """Every role × ``app.model:action`` cell the screen and the API show."""

    roles: list[MatrixRole]
    models: list[MatrixModel]
    cells: dict[tuple[str, str], Cell]

    def cell(self, role: str, permission: str) -> Cell:
        found = self.cells.get((role, permission))
        if found is None:
            return Cell(role, permission, None, None, None, False)
        return found

    def to_dict(self) -> dict[str, Any]:
        grants: dict[str, dict[str, Any]] = {role.slug: {} for role in self.roles}
        for (slug, key), cell in self.cells.items():
            grants.setdefault(slug, {})[key] = cell.to_dict()
        return {
            "roles": [role.to_dict() for role in self.roles],
            "models": [model.to_dict() for model in self.models],
            "grants": grants,
        }


def scope_value(scope: str, scope_path: str = "") -> str | None:
    """``"all"``, ``"own"``, ``"related:venue"``, ``"custom:published"``; ``None`` for ``none``."""
    if scope == NONE_SCOPE:
        return None
    return f"{scope}:{scope_path}" if scope_path else scope


def _scope_parts(value: str) -> tuple[str, str]:
    kind, _, path = value.partition(":")
    return kind, path


def scope_options(model: type[models.Model]) -> list[tuple[str, str]]:
    """The scopes a grant on ``model`` may take, as ``(value, label)`` pairs."""
    options = [("all", "All rows")]
    owner = owner_field(model)
    if owner:
        options.append(("own", f"Own rows ({owner})"))
    options.extend((f"related:{key}", f"Related: {key}") for key in scope_paths(model))
    options.extend((f"custom:{name}", f"Custom: {name}") for name in custom_scopes())
    return options


def _excluded(model: type[models.Model], exclude: frozenset[str]) -> bool:
    opts = model._meta
    lowered = {entry.lower() for entry in exclude}
    return opts.app_label in exclude or opts.label in exclude or opts.label_lower in lowered


def matrix_models() -> dict[str, type[models.Model]]:
    """``label_lower`` → model for each model shown (``KARNI_MATRIX_EXCLUDE`` applied)."""
    exclude = frozenset(getattr(settings, "KARNI_MATRIX_EXCLUDE", DEFAULT_MATRIX_EXCLUDE))
    found: dict[str, type[models.Model]] = {}
    for key, model in permission_keys().items():
        label = key.rsplit(":", 1)[0]
        if label in found or _excluded(model, exclude):
            continue
        found[label] = model
    ordered = sorted(found.items(), key=lambda item: (item[1]._meta.app_label, item[0]))
    return dict(ordered)


@dataclass(frozen=True)
class _Declaration:
    system: frozenset[str]
    grants: dict[str, dict[str, str]]


def _declared_value(grant: Grant) -> str:
    return f"{grant.scope}:{grant.scope_path}" if grant.scope_path else grant.scope


def _declaration() -> _Declaration:
    keys = permission_keys()
    system: set[str] = set()
    grants: dict[str, dict[str, str]] = {}
    for spec in declared_roles():
        if spec.system:
            system.add(spec.slug)
        grants[spec.slug] = {g.permission: _declared_value(g) for g in expand_grants(spec, keys)}
    return _Declaration(frozenset(system), grants)


def build_matrix() -> Matrix:
    """The current matrix: roles from the database, cells from the grant rows."""
    from karni.accounts.models import Role, RolePermission

    declaration = _declaration()
    roles = [
        MatrixRole(role.slug, role.name, role.is_system, role.description)
        for role in Role.objects.order_by("slug")
    ]
    columns = [
        MatrixModel(
            label,
            str(model._meta.verbose_name),
            model._meta.app_label,
            model_actions(model),
            tuple(scope_options(model)),
        )
        for label, model in matrix_models().items()
    ]
    rows = RolePermission.objects.filter(
        role__slug__in=[role.slug for role in roles]
    ).select_related("role", "permission__content_type")
    current = {(row.role.slug, row.permission.key): row for row in rows}
    cells: dict[tuple[str, str], Cell] = {}
    for role in roles:
        declared = declaration.grants.get(role.slug, {})
        locked_role = role.slug in declaration.system
        for column in columns:
            for action in column.actions:
                key = column.permission(action)
                row = current.get((role.slug, key))
                cells[(role.slug, key)] = Cell(
                    role=role.slug,
                    permission=key,
                    scope=scope_value(row.scope, row.scope_path) if row is not None else None,
                    origin=row.origin if row is not None else None,
                    declared=declared.get(key),
                    locked=locked_role and key in declared,
                )
    return Matrix(roles, columns, cells)


# changes


@dataclass(frozen=True)
class Change:
    """One cell's move: scope and origin before, scope and origin after."""

    role: str
    permission: str
    before: str | None
    after: str | None
    before_origin: str | None
    after_origin: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "permission": self.permission,
            "before": self.before,
            "after": self.after,
            "before_origin": self.before_origin,
            "after_origin": self.after_origin,
        }


@dataclass(frozen=True)
class Refusal:
    """A requested change a guard rail refused, and why."""

    role: str
    permission: str
    requested: str | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "permission": self.permission,
            "requested": self.requested,
            "reason": self.reason,
        }


@dataclass
class Plan:
    """What a request would change, and what it may not."""

    changes: list[Change] = field(default_factory=list)
    refusals: list[Refusal] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.refusals

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "changes": [change.to_dict() for change in self.changes],
            "refusals": [refusal.to_dict() for refusal in self.refusals],
        }


class MatrixRefused(KarniValueError):
    """:func:`apply_changes` refused the request; ``plan`` says which changes and why."""

    def __init__(self, plan: Plan) -> None:
        self.plan = plan
        reasons = "; ".join(f"{r.role} {r.permission}: {r.reason}" for r in plan.refusals)
        super().__init__(
            f"The permission matrix refused {len(plan.refusals)} change(s): {reasons}",
            code="E213",
        )


Requested = Iterable[tuple[str, str, str | None]]


def _grant_value(grant: Grant) -> str | None:
    return scope_value(grant.scope, grant.scope_path)


def _covers(grants: list[Grant], value: str) -> bool:
    return any(grant.scope == "all" or _grant_value(grant) == value for grant in grants)


def _origin_after(cell: Cell, after: str | None) -> str | None:
    if after is None:
        return _ORIGIN_MATRIX if cell.declared is not None else None
    return _ORIGIN_DECLARED if after == cell.declared else _ORIGIN_MATRIX


def plan_changes(operator: Any, requested: Requested, *, matrix: Matrix | None = None) -> Plan:
    """The diff ``requested`` cells would make for ``operator``, guard rails applied.

    ``requested`` is ``(role slug, "app.model:action", value)`` triples where
    ``value`` is a scope (``"all"``, ``"own"``, ``"related:<key>"``,
    ``"custom:<name>"``), ``None`` to revoke, or :data:`DECLARED` to hand the
    cell back to ``KARNI_ROLES``. Cells already in the requested state are
    not changes; a later triple for the same cell replaces an earlier one.
    """
    from karni.accounts.permissions import user_roles

    matrix = matrix if matrix is not None else build_matrix()
    by_label = {model.label: model for model in matrix.models}
    roles = {role.slug for role in matrix.roles}
    held = grants_for(operator)
    superuser = bool(getattr(operator, "is_superuser", False))
    plan = Plan()
    wanted: dict[tuple[str, str], str | None] = {}
    for role, permission, value in requested:
        wanted[(str(role), str(permission))] = value

    for (role, permission), value in wanted.items():
        if role not in roles:
            plan.refusals.append(Refusal(role, permission, value, f"unknown role {role!r}."))
            continue
        label, _, action = permission.rpartition(":")
        column = by_label.get(label)
        if column is None or action not in column.actions:
            plan.refusals.append(
                Refusal(role, permission, value, f"unknown permission {permission!r}.")
            )
            continue
        cell = matrix.cell(role, permission)
        available = [option for option, _ in column.scopes]
        after: str | None
        if value == DECLARED:
            after = cell.declared
        elif value is None:
            after = None
        elif value in available:
            after = value
        else:
            plan.refusals.append(
                Refusal(
                    role,
                    permission,
                    value,
                    f"scope {value!r} is not available for {label}; choose from "
                    f"{', '.join(available)}.",
                )
            )
            continue
        after_origin = _origin_after(cell, after)
        if (cell.scope, cell.origin) == (after, after_origin):
            continue
        if cell.locked:
            plan.refusals.append(
                Refusal(
                    role,
                    permission,
                    value,
                    f"{role} is a system role; {permission} = {cell.declared} is declared in "
                    "KARNI_ROLES and cannot be changed here. Change the declaration.",
                )
            )
            continue
        if not superuser:
            grants = held.get(permission, [])
            if not grants:
                plan.refusals.append(
                    Refusal(
                        role,
                        permission,
                        value,
                        f"you do not hold {permission}, so you cannot grant or revoke it.",
                    )
                )
                continue
            if after is not None and not _covers(grants, after):
                mine = sorted({_grant_value(grant) or "" for grant in grants})
                plan.refusals.append(
                    Refusal(
                        role,
                        permission,
                        value,
                        f"you hold {permission} only as {', '.join(mine)}; you cannot grant "
                        f"{after}.",
                    )
                )
                continue
        plan.changes.append(Change(role, permission, cell.scope, after, cell.origin, after_origin))

    if not superuser and held.get(f"{MATRIX_PERMISSION}:change"):
        _refuse_lockout(plan, matrix, set(user_roles(operator)))
    return plan


def _refuse_lockout(plan: Plan, matrix: Matrix, mine: set[str]) -> None:
    """Move every change that would leave the operator unable to change permissions."""
    key = f"{MATRIX_PERMISSION}:change"
    after: dict[str, str | None] = {slug: matrix.cell(slug, key).scope for slug in mine}
    for change in plan.changes:
        if change.role in mine and change.permission == key:
            after[change.role] = change.after
    if any(value is not None for value in after.values()):
        return
    kept: list[Change] = []
    for change in plan.changes:
        if change.role in mine and change.permission == key and change.after is None:
            plan.refusals.append(
                Refusal(
                    change.role,
                    change.permission,
                    None,
                    f"this would remove your own last permission to change permissions "
                    f"({key} through {change.role}).",
                )
            )
        else:
            kept.append(change)
    plan.changes = kept


def apply_changes(operator: Any, requested: Requested) -> Plan:
    """Write the changes ``requested`` describes, all of them or none.

    Raises :class:`MatrixRefused` (``E213``) when any change is refused; the
    exception's ``plan`` says which and why. Every row written is recorded
    by ``karni.audit`` with ``operator`` as the actor.
    """
    from django.contrib.contenttypes.models import ContentType

    from karni.accounts.models import Permission, Role, RolePermission

    with transaction.atomic(), current_user(operator):
        matrix = build_matrix()
        plan = plan_changes(operator, requested, matrix=matrix)
        if not plan.ok:
            raise MatrixRefused(plan)
        if not plan.changes:
            return plan
        roles = {
            role.slug: role for role in Role.objects.filter(slug__in={c.role for c in plan.changes})
        }
        targets = matrix_models()
        for change in plan.changes:
            label, _, action = change.permission.rpartition(":")
            permission, _ = Permission.objects.get_or_create(
                content_type=ContentType.objects.get_for_model(targets[label]), action=action
            )
            row = (
                RolePermission._base_manager.filter(role=roles[change.role], permission=permission)
                .order_by("pk")
                .first()
            )
            if change.after_origin is None:
                if row is not None:
                    row.hard_delete()
                continue
            scope, path = (NONE_SCOPE, "") if change.after is None else _scope_parts(change.after)
            if row is None:
                RolePermission.objects.create(
                    role=roles[change.role],
                    permission=permission,
                    scope=scope,
                    scope_path=path,
                    origin=change.after_origin,
                )
                continue
            row.scope, row.scope_path, row.origin, row.deleted_at = (
                scope,
                path,
                change.after_origin,
                None,
            )
            row.save(update_fields=["scope", "scope_path", "origin", "deleted_at", "updated_at"])
    if hasattr(operator, "_karni_grants"):
        delattr(operator, "_karni_grants")  # the operator's next check sees the result
    return plan


# effective permissions


@dataclass(frozen=True)
class Source:
    """Why a user holds a permission: the role, its scope and where that grant came from."""

    role: str
    role_name: str
    scope: str | None
    origin: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "role_name": self.role_name,
            "scope": self.scope,
            "origin": self.origin,
        }


@dataclass(frozen=True)
class Effective:
    """One permission as the user holds it: the effective scope and every source."""

    permission: str
    model: str
    action: str
    scope: str | None
    sources: tuple[Source, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "permission": self.permission,
            "model": self.model,
            "action": self.action,
            "scope": self.scope,
            "sources": [source.to_dict() for source in self.sources],
        }


@dataclass
class EffectiveReport:
    """What one user may do, permission by permission, and why."""

    user_id: str
    username: str
    superuser: bool
    roles: list[str]
    entries: list[Effective]

    def to_dict(self) -> dict[str, Any]:
        return {
            "user": {"id": self.user_id, "username": self.username},
            "superuser": self.superuser,
            "roles": self.roles,
            "permissions": [entry.to_dict() for entry in self.entries],
        }


def effective_permissions(user: Any) -> EffectiveReport:
    """Every matrix permission for ``user``: the effective scope and the roles behind it.

    A superuser holds everything with scope ``all`` (the admin's own
    convention); for everyone else the sources are the grant rows of the
    user's roles, including a cell the matrix revoked (scope ``None``,
    origin ``matrix``) so "why can't this person…" is answered too.
    """
    from karni.accounts.models import RolePermission
    from karni.accounts.permissions import user_roles

    superuser = bool(getattr(user, "is_superuser", False))
    sources: dict[str, list[Source]] = {}
    if not superuser and getattr(user, "is_authenticated", False):
        rows = RolePermission.objects.filter(role__group__in=user.groups.all()).select_related(
            "role", "permission__content_type"
        )
        for row in rows:
            sources.setdefault(row.permission.key, []).append(
                Source(
                    row.role.slug, row.role.name, scope_value(row.scope, row.scope_path), row.origin
                )
            )
    entries: list[Effective] = []
    for label, model in matrix_models().items():
        for action in model_actions(model):
            key = f"{label}:{action}"
            if superuser:
                entries.append(
                    Effective(
                        key, label, action, "all", (Source("", "superuser", "all", "superuser"),)
                    )
                )
                continue
            found = tuple(
                sorted(sources.get(key, ()), key=lambda source: (source.scope is None, source.role))
            )
            values = list(dict.fromkeys(s.scope for s in found if s.scope is not None))
            scope = "all" if "all" in values else (" | ".join(values) or None)
            entries.append(Effective(key, label, action, scope, found))
    username = str(getattr(user, "email", "") or user.get_username())
    return EffectiveReport(
        str(user.pk),
        username,
        superuser,
        user_roles(user) if not superuser else user_roles(user),
        entries,
    )


# the matrix's own history


def recent_changes(limit: int = 20) -> list[dict[str, Any]]:
    """The latest ``karni.audit`` entries on grant rows, resolved to role and permission names."""
    if not apps.is_installed("karni.audit"):
        return []
    from django.contrib.contenttypes.models import ContentType

    from karni.accounts.models import Permission, Role, RolePermission
    from karni.audit.models import ChangeLog

    content_type = ContentType.objects.get_for_model(RolePermission)
    entries = list(
        ChangeLog.objects.filter(content_type=content_type).select_related("actor")[:limit]
    )
    if not entries:
        return []
    rows = {
        str(row.pk): row
        for row in RolePermission._base_manager.filter(
            pk__in=[entry.object_id for entry in entries]
        ).select_related("role", "permission__content_type")
    }
    role_pks = {str(pk) for entry in entries for pk in entry.diff.get("role", []) if pk}
    permission_pks = {str(pk) for entry in entries for pk in entry.diff.get("permission", []) if pk}
    roles = {str(role.pk): role for role in Role._base_manager.filter(pk__in=role_pks)}
    permissions = {
        str(p.pk): p
        for p in Permission._base_manager.filter(pk__in=permission_pks).select_related(
            "content_type"
        )
    }

    def side(entry: Any, row: Any, name: str, index: int, default: str) -> str:
        if name in entry.diff:
            value = entry.diff[name][index]
            return str(value) if value is not None else default
        return str(getattr(row, name, default)) if row is not None else default

    found: list[dict[str, Any]] = []
    for entry in entries:
        row = rows.get(entry.object_id)
        role_pk = next((str(pk) for pk in entry.diff.get("role", []) if pk), None)
        permission_pk = next((str(pk) for pk in entry.diff.get("permission", []) if pk), None)
        role = roles.get(role_pk or "") or (row.role if row is not None else None)
        permission = permissions.get(permission_pk or "") or (
            row.permission if row is not None else None
        )
        before = (
            None
            if entry.action == "create"
            else scope_value(
                side(entry, row, "scope", 0, NONE_SCOPE), side(entry, row, "scope_path", 0, "")
            )
        )
        after = (
            None
            if entry.action == "delete"
            else scope_value(
                side(entry, row, "scope", 1, NONE_SCOPE), side(entry, row, "scope_path", 1, "")
            )
        )
        found.append(
            {
                "timestamp": entry.timestamp,
                "actor": entry.actor,
                "action": entry.action,
                "role": role.slug if role is not None else "?",
                "permission": permission.key if permission is not None else "?",
                "before": before,
                "after": after,
            }
        )
    return found
