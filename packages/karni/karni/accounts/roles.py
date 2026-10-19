"""Roles as data: the declared role set, its grants, and what a user may do.

A project declares its roles once, in the ``KARNI_ROLES`` setting::

    KARNI_ROLES = {
        "staff": {"name": "Staff", "system": True, "grants": {"*": "all"}},
        "manager": {"name": "Branch manager", "grants": {"shop.order:*": "related:branch"}},
        "customer": {"grants": {"shop.order:view": "own", "shop.order:add": "all"}},
    }

A grant maps a permission pattern (``app_label.model:action``, with ``*`` for
either part) to a **scope** — which rows the action reaches:

======================  =====================================================
``all``                 every row
``own``                 rows whose owner field (``Karni.owner_field``) is the user
``related:<key>``       rows whose ``Karni.scope_paths[key]`` equals the user's
                        attribute of the same name (``user.branch`` → ``order.branch``)
``custom:<name>``       a callable registered with :func:`register_scope`
======================  =====================================================

``karni sync-roles`` (``manage.py karni_sync_roles``) expands the patterns
against every model and its actions (the standard four plus
``Karni.actions``) into :class:`~karni.accounts.models.Role`,
:class:`~karni.accounts.models.Permission` and
:class:`~karni.accounts.models.RolePermission` rows — creating and updating,
reporting what the database holds that the declaration no longer does, and
never deleting a role. The sync also runs after ``migrate``
(``KARNI_ROLES_AUTOSYNC``). A grant the permission matrix set
(``origin = "matrix"``, :mod:`karni.accounts.matrix`) is the operator's
decision: the sync keeps it and reports it as overridden.

At request time :func:`grants_for` resolves a user's grants once (cached on
the user instance, so once per request); :func:`user_can` answers the gate
and :func:`rows_for` compiles the scopes into a ``Q`` for the row filter.
Nothing here compares a role to a literal: ``staff``/``user``/``customer``
are only the default *value* of ``KARNI_ROLES``, in ``karni.conf.base``.

Override / escape hatch: replace ``KARNI_ROLES`` entirely; register custom
scopes; call :func:`sync_roles` yourself with your own declaration.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from django.apps import apps
from django.db import models, transaction
from django.db.models import Q

from karni.exceptions import KarniImproperlyConfigured, KarniValueError
from karni.meta import model_actions, owner_field, permission_key, scope_paths

__all__ = [
    "Grant",
    "SCOPES",
    "SyncReport",
    "custom_scopes",
    "declared_roles",
    "grants_for",
    "permission_keys",
    "register_scope",
    "requires",
    "rows_for",
    "sync_roles",
    "user_can",
]

SETTING: Final = "KARNI_ROLES"
SCOPES: Final[tuple[str, ...]] = ("all", "own", "related", "custom")

#: The scope of a declared grant the permission matrix revoked: a row that
#: grants nothing, kept so the sync does not restore the declaration.
NONE_SCOPE: Final = "none"

#: ``custom:<name>`` scopes: name → ``fn(user, model) -> Q | bool``.
_custom_scopes: dict[str, Callable[[Any, type[models.Model]], Q | bool]] = {}


def register_scope(name: str, fn: Callable[[Any, type[models.Model]], Q | bool]) -> None:
    """Register the callable behind ``custom:<name>``; it returns a ``Q`` (or a bool)."""
    _custom_scopes[name] = fn


def custom_scopes() -> tuple[str, ...]:
    """The names registered with :func:`register_scope`, sorted."""
    return tuple(sorted(_custom_scopes))


# the declaration


@dataclass(frozen=True)
class RoleSpec:
    slug: str
    name: str
    description: str
    system: bool
    grants: Mapping[str, str]


@dataclass(frozen=True)
class Grant:
    """One resolved grant: ``permission`` (``app.model:action``) reached with ``scope``."""

    permission: str
    scope: str
    scope_path: str = ""


def _scope_parts(scope: str, where: str) -> tuple[str, str]:
    kind, _, path = str(scope).partition(":")
    if kind not in SCOPES or (kind in ("related", "custom")) != bool(path):
        raise KarniImproperlyConfigured(
            f"{SETTING}: {where} has scope {scope!r}; a scope is 'all', 'own', "
            "'related:<scope path key>' or 'custom:<registered name>'.",
            code="E205",
        )
    return kind, path


def declared_roles(declaration: Mapping[str, Any] | None = None) -> list[RoleSpec]:
    """The role set from ``KARNI_ROLES`` (or ``declaration``), validated."""
    from django.conf import settings

    raw = declaration if declaration is not None else getattr(settings, SETTING, None) or {}
    if not isinstance(raw, Mapping):
        raise KarniImproperlyConfigured(
            f"{SETTING} must be a dict of role slug -> {{name, description, system, grants}}, "
            f"got {type(raw).__name__}.",
            code="E205",
        )
    found: list[RoleSpec] = []
    for slug, spec in raw.items():
        if not isinstance(slug, str) or not slug or not isinstance(spec, Mapping):
            raise KarniImproperlyConfigured(
                f"{SETTING}[{slug!r}] must be a dict ({{'name': ..., 'grants': {{...}}}}).",
                code="E205",
            )
        grants = spec.get("grants") or {}
        if not isinstance(grants, Mapping):
            raise KarniImproperlyConfigured(
                f"{SETTING}[{slug!r}]['grants'] must map 'app.model:action' patterns to scopes.",
                code="E205",
            )
        for pattern, scope in grants.items():
            if not isinstance(pattern, str) or ":" not in pattern and pattern != "*":
                raise KarniImproperlyConfigured(
                    f"{SETTING}[{slug!r}]: grant pattern {pattern!r} must look like "
                    "'app_label.model:action', with '*' for either part (or '*' alone).",
                    code="E205",
                )
            _scope_parts(str(scope), f"role {slug!r}, grant {pattern!r}")
        found.append(
            RoleSpec(
                slug=slug,
                name=str(spec.get("name") or slug.replace("_", " ").replace("-", " ").title()),
                description=str(spec.get("description") or ""),
                system=bool(spec.get("system", False)),
                grants={str(k): str(v) for k, v in grants.items()},
            )
        )
    return found


def _permission_models() -> list[type[models.Model]]:
    """Every concrete, non-auto-created model that can carry permissions."""
    return [
        model
        for model in apps.get_models()
        if not model._meta.auto_created and not model._meta.proxy and not model._meta.abstract
    ]


def permission_keys() -> dict[str, type[models.Model]]:
    """Every ``app.model:action`` key in the project (standard + ``Karni.actions``) → model."""
    return {
        permission_key(model, action): model
        for model in _permission_models()
        for action in model_actions(model)
    }


def expand_grants(spec: RoleSpec, keys: Mapping[str, type[models.Model]]) -> list[Grant]:
    """Resolve a role's patterns against the project's permission keys.

    Later, more specific patterns win over earlier wildcards for the same key
    (``{"*": "own", "shop.order:approve": "all"}``). A pattern that matches
    nothing is an error (``E206``): a typo must not grant silently. An
    explicit key whose model cannot carry the scope (``own`` without an owner
    field, ``related:branch`` without that scope path) is an error too; a
    wildcard simply skips such models — ``"*": "own"`` means "everything
    that can be owned".
    """
    resolved: dict[str, Grant] = {}
    for pattern, scope in spec.grants.items():
        glob = "*:*" if pattern == "*" else pattern
        explicit = "*" not in glob.split(":", 1)[0]
        matched = [key for key in keys if fnmatch.fnmatchcase(key, glob)]
        if not matched:
            raise KarniImproperlyConfigured(
                f"{SETTING}[{spec.slug!r}]: grant pattern {pattern!r} matches no permission. "
                "Keys look like 'events.event:view'; a model's extra actions come from "
                "`class Karni: actions = [...]`.",
                code="E206",
            )
        kind, path = _scope_parts(scope, f"role {spec.slug!r}, grant {pattern!r}")
        for key in matched:
            model = keys[key]
            if kind == "own" and owner_field(model) is None:
                if not explicit:
                    continue
                raise KarniImproperlyConfigured(
                    f"{SETTING}[{spec.slug!r}]: {key!r} is granted with scope 'own', but "
                    f"{model.__name__} has no owner field. Declare `class Karni: "
                    "owner_field = '<fk to the user>'` on the model, or grant 'all'.",
                    code="E206",
                )
            if kind == "related" and path not in scope_paths(model):
                if not explicit:
                    continue
                raise KarniImproperlyConfigured(
                    f"{SETTING}[{spec.slug!r}]: {key!r} is granted with scope "
                    f"'related:{path}', but {model.__name__} declares no scope path "
                    f"{path!r}. Add `class Karni: scope_paths = {{{path!r}: '<lookup>'}}`.",
                    code="E206",
                )
            resolved[key] = Grant(key, kind, path)
    return list(resolved.values())


# sync


@dataclass
class SyncReport:
    created_roles: list[str] = field(default_factory=list)
    updated_roles: list[str] = field(default_factory=list)
    created_permissions: int = 0
    grants: dict[str, int] = field(default_factory=dict)
    undeclared_roles: list[str] = field(default_factory=list)
    overridden: list[str] = field(default_factory=list)
    dry_run: bool = False

    def render(self) -> str:
        verb = "Would sync" if self.dry_run else "Synced"
        lines = [
            f"{verb} {len(self.grants)} role(s), {self.created_permissions} new permission(s)."
        ]
        for slug, count in self.grants.items():
            state = (
                "new"
                if slug in self.created_roles
                else "updated"
                if slug in self.updated_roles
                else "unchanged"
            )
            lines.append(f"  {slug:<20} {count:>4} grant(s)  {state}")
        if self.undeclared_roles:
            lines.append(
                "In the database but not in KARNI_ROLES (kept; remove them yourself if unwanted): "
                + ", ".join(self.undeclared_roles)
            )
        if self.overridden:
            lines.append(
                "Set in the permission matrix, so the declaration does not apply (kept): "
                + ", ".join(self.overridden)
            )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_roles": self.created_roles,
            "updated_roles": self.updated_roles,
            "created_permissions": self.created_permissions,
            "grants": self.grants,
            "undeclared_roles": self.undeclared_roles,
            "overridden": self.overridden,
            "dry_run": self.dry_run,
        }


def _overridden(specs: list[RoleSpec]) -> list[str]:
    """``"<role> <permission>"`` for every declared role's grant the matrix owns."""
    from karni.accounts.models import RolePermission

    rows = (
        RolePermission.objects.filter(
            role__slug__in=[spec.slug for spec in specs], origin=RolePermission.Origin.MATRIX
        )
        .select_related("role", "permission__content_type")
        .order_by("role__slug")
    )
    return [f"{row.role.slug} {row.permission.key}" for row in rows]


def sync_roles(
    declaration: Mapping[str, Any] | None = None, *, dry_run: bool = False
) -> SyncReport:
    """Reconcile the database with the declared roles: create, update, report; never delete a role.

    A grant with ``origin = "matrix"`` (set in the permission matrix) is left
    exactly as it is — whatever the declaration says for that cell — and
    listed in the report. A declared grant the declaration dropped is
    removed outright (a soft-deleted row would still hold the unique
    constraint and block a later re-grant).
    """
    from django.contrib.auth.models import Group
    from django.contrib.contenttypes.models import ContentType

    from karni.accounts.models import Permission, Role, RolePermission

    specs = declared_roles(declaration)
    keys = permission_keys()
    report = SyncReport(dry_run=dry_run)
    expanded = {spec.slug: expand_grants(spec, keys) for spec in specs}
    if dry_run:
        for spec in specs:
            report.grants[spec.slug] = len(expanded[spec.slug])
            if not Role.objects.filter(slug=spec.slug).exists():
                report.created_roles.append(spec.slug)
        report.undeclared_roles = sorted(
            set(Role.objects.values_list("slug", flat=True)) - {spec.slug for spec in specs}
        )
        report.overridden = _overridden(specs)
        return report

    matrix_origin = RolePermission.Origin.MATRIX
    with transaction.atomic():
        permissions: dict[str, Permission] = {}
        for key, model in keys.items():
            content_type = ContentType.objects.get_for_model(model)
            permission, created = Permission.objects.get_or_create(
                content_type=content_type, action=key.rsplit(":", 1)[1]
            )
            permissions[key] = permission
            report.created_permissions += int(created)
        for spec in specs:
            group, _ = Group.objects.get_or_create(name=spec.slug)
            role, created = Role.objects.get_or_create(
                slug=spec.slug,
                defaults={
                    "group": group,
                    "name": spec.name,
                    "description": spec.description,
                    "is_system": spec.system,
                },
            )
            changed = False
            for attr, value in (
                ("group", group),
                ("name", spec.name),
                ("description", spec.description),
                ("is_system", spec.system),
            ):
                if getattr(role, attr) != value:
                    setattr(role, attr, value)
                    changed = True
            if changed and not created:
                role.save()
                report.updated_roles.append(spec.slug)
            if created:
                report.created_roles.append(spec.slug)
            wanted = {grant.permission: grant for grant in expanded[spec.slug]}
            # The base manager: a soft-deleted row still holds the unique
            # constraint, so it is revived rather than duplicated.
            existing = {
                rp.permission_id: rp
                for rp in RolePermission._base_manager.filter(role=role).select_related(
                    "permission"
                )
            }
            for key, grant in wanted.items():
                permission = permissions[key]
                row = existing.get(permission.pk)
                if row is None:
                    RolePermission.objects.create(
                        role=role,
                        permission=permission,
                        scope=grant.scope,
                        scope_path=grant.scope_path,
                    )
                    if not created and spec.slug not in report.updated_roles:
                        report.updated_roles.append(spec.slug)
                elif row.origin == matrix_origin and row.deleted_at is None:
                    report.overridden.append(f"{spec.slug} {key}")
                elif (row.scope, row.scope_path, row.origin, row.deleted_at) != (
                    grant.scope,
                    grant.scope_path,
                    RolePermission.Origin.DECLARED,
                    None,
                ):
                    row.scope, row.scope_path = grant.scope, grant.scope_path
                    row.origin, row.deleted_at = RolePermission.Origin.DECLARED, None
                    row.save(
                        update_fields=["scope", "scope_path", "origin", "deleted_at", "updated_at"]
                    )
                    if spec.slug not in report.updated_roles:
                        report.updated_roles.append(spec.slug)
            wanted_pks = {permissions[k].pk for k in wanted}
            stale = [
                rp
                for pid, rp in existing.items()
                if pid not in wanted_pks
                and not (rp.origin == matrix_origin and rp.deleted_at is None)
            ]
            if stale:
                RolePermission._base_manager.filter(pk__in=[rp.pk for rp in stale]).delete()
                if spec.slug not in report.updated_roles and any(
                    rp.deleted_at is None for rp in stale
                ):
                    report.updated_roles.append(spec.slug)
            report.grants[spec.slug] = len(wanted)
        report.undeclared_roles = sorted(
            set(Role.objects.values_list("slug", flat=True)) - {spec.slug for spec in specs}
        )
    return report


# what a user may do

_CACHE_ATTR: Final = "_karni_grants"


def grants_for(user: Any) -> dict[str, list[Grant]]:
    """The user's grants by permission key, resolved once per user instance (so per request).

    Anonymous users hold nothing. Superusers hold every permission with scope
    ``all`` — the admin's own convention, kept so a superuser is never locked
    out by an incomplete declaration.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return {}
    cached = getattr(user, _CACHE_ATTR, None)
    if cached is not None:
        return cached
    from karni.accounts.models import RolePermission

    found: dict[str, list[Grant]] = {}
    if getattr(user, "is_superuser", False):
        for key in permission_keys():
            found[key] = [Grant(key, "all")]
    else:
        rows = RolePermission.objects.filter(role__group__in=user.groups.all()).select_related(
            "permission", "permission__content_type"
        )
        for row in rows:
            if row.scope == NONE_SCOPE:
                continue  # revoked in the permission matrix: grants nothing
            key = row.permission.key
            found.setdefault(key, []).append(Grant(key, row.scope, row.scope_path))
    setattr(user, _CACHE_ATTR, found)
    return found


def _resolve_key(action: str, model: type[models.Model] | None, obj: Any) -> str:
    if ":" in action:
        return action
    target = model if model is not None else type(obj) if obj is not None else None
    if target is None:
        raise KarniValueError(
            f"can({action!r}) needs the model: pass 'app_label.model:{action}', or obj=/model=.",
            code="E207",
        )
    return permission_key(target, action)


def _grant_q(user: Any, model: type[models.Model], grant: Grant) -> Q | bool:
    if grant.scope == "all":
        return True
    if grant.scope == "own":
        owner = owner_field(model)
        return Q(**{owner: user}) if owner else False
    if grant.scope == "related":
        path = scope_paths(model).get(grant.scope_path)
        value = getattr(user, grant.scope_path, None)
        if path is None or value is None:
            return False  # fail closed: the user has no branch to be related through
        return Q(**{path: value})
    fn = _custom_scopes.get(grant.scope_path)
    if fn is None:
        raise KarniImproperlyConfigured(
            f"Scope 'custom:{grant.scope_path}' is granted but no scope of that name is "
            f"registered. Call karni.accounts.roles.register_scope({grant.scope_path!r}, fn) "
            "at startup (an app's ready() or listeners.py).",
            code="E206",
        )
    return fn(user, model)


def rows_for(user: Any, model: type[models.Model], action: str) -> Q | bool:
    """The rows ``user`` reaches for ``action`` on ``model``: ``True``, ``False`` or a ``Q``.

    The union of the user's grants for that permission; no grant → ``False``.
    """
    grants = grants_for(user).get(permission_key(model, action), [])
    rows: Q | bool = False
    for grant in grants:
        part = _grant_q(user, model, grant)
        if part is True:
            return True
        if part is False:
            continue
        rows = part if rows is False else rows | part
    return rows


def user_can(
    user: Any, action: str, obj: Any = None, *, model: type[models.Model] | None = None
) -> bool:
    """May ``user`` perform ``action``? With ``obj``, is that row inside the grant's scope?

    ``action`` is ``"app_label.model:action"``, or just ``"approve"`` with
    ``obj=`` or ``model=`` naming the model.
    """
    key = _resolve_key(action, model, obj)
    grants = grants_for(user).get(key)
    if not grants:
        return False
    if obj is None:
        return True
    target = type(obj)
    rows = rows_for(user, target, key.rsplit(":", 1)[1])
    if rows is True:
        return True
    if rows is False:
        return False
    return target._default_manager.filter(rows, pk=obj.pk).exists()


def requires(action: str, *, model: type[models.Model] | None = None) -> Callable[[Any], Any]:
    """Guard a view method or a service function with a permission.

    On a DRF view or Django view (first argument carries ``.request`` or
    is a request), the request's user is checked; on a plain function, the
    current user from :func:`karni.middleware.get_current_user`. Denial
    raises DRF's ``PermissionDenied`` (a 403 in a view; an exception in a
    service, which the API layer turns into a 403 as well).
    """
    from functools import wraps

    from rest_framework.exceptions import PermissionDenied

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def guarded(*args: Any, **kwargs: Any) -> Any:
            user = _user_from(args)
            if not user_can(user, action, model=model):
                raise PermissionDenied(
                    detail=f"This action requires the permission {action!r}.", code="E208"
                )
            return fn(*args, **kwargs)

        return guarded

    return decorate


def _user_from(args: Iterable[Any]) -> Any:
    from karni.middleware import get_current_user

    for candidate in args:
        request = getattr(candidate, "request", candidate)
        user = getattr(request, "user", None)
        if user is not None and hasattr(user, "is_authenticated"):
            return user
    return get_current_user()
