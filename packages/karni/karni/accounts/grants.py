"""Experimental. Per-user grants: access given to one user, alongside the grants of their roles.

A role grant reaches everyone who holds the role. A large app also grants
access user by user: this customer sees these regions, that analyst sees
these report sections until the end of the quarter. A
:class:`~karni.accounts.models.UserGrant` row is such a grant: a permission
pattern and a scope written as in ``KARNI_ROLES``, plus ``targets`` (row ids,
for a scope that points at rows), ``expires_at``, ``granted_by`` and
``reason``. Every change is history (``karni.audit``).

While ``KARNI_USER_GRANTS`` is on, :func:`karni.accounts.roles.grants_for`
adds the user's live grants to their role grants, so ``Granted()``, ``Can``,
``user.can``, ``@requires`` and the admin's row scope answer with the union.
The grants load once per request with the role grants: one more query
however many checks the request makes. Off (the default), nothing here runs
and a request pays no query for it.

Targets: a ``related:<key>`` grant reaches the rows whose
``Karni.scope_paths[key]`` equals ``user.<key>``. With targets it reaches the
rows whose scope path is one of the targets instead. A ``tree:<path>`` grant
(experimental, :mod:`karni.accounts.tree_scope`) reaches the rows under its
target nodes, or under ``user.<path>`` without targets. A scope that points
at no row (``all``, ``own``, ``custom:<name>``) takes no targets
(:data:`TARGETED_SCOPES`).

Writing: :func:`grant`, :func:`bulk_grant`, :func:`change`, :func:`expire`
and :func:`revoke` take the operator explicitly, check the pattern, the
scope and the targets (:func:`check`: ``E360``, ``E361``, ``E362``) and
refuse what the operator does not hold (``E363``), as the permission matrix
does. ``operator=None`` is the code itself (a seed, a migration, a test):
nothing is refused for it and ``granted_by`` stays empty.

Reading: :func:`scope_targets` answers, for one user and one scope, which
target ids the user's role grants and user grants give, and which grant gave
each. A scope that compiles to "these rows" (``related:<key>`` and
``tree:<path>``) and a menu built from grants read it.

Override / escape hatch: ``KARNI_USER_GRANTS = False`` turns the tier off
without touching the rows. Every function here is plain data in and out, so
a project's own screen or a seed script calls them directly.
"""

from __future__ import annotations

import fnmatch
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction

from karni.accounts.roles import (
    _PATH_SCOPES,
    NONE_SCOPE,
    SCOPES,
    Grant,
    GrantSource,
    custom_scopes,
    grants_for,
    permission_keys,
)
from karni.exceptions import KarniTypeError, KarniValueError
from karni.meta import model_actions, owner_field, permission_key, scope_paths
from karni.middleware import current_user

if TYPE_CHECKING:
    from karni.accounts.models import UserGrant

__all__ = [
    "GRANT_PERMISSION",
    "ORIGIN",
    "SETTING",
    "TARGETED_SCOPES",
    "Checked",
    "GrantRefused",
    "TargetGrant",
    "bulk_grant",
    "change",
    "check",
    "enabled",
    "expire",
    "forget",
    "grant",
    "live_rows",
    "normalise_targets",
    "refusals",
    "revoke",
    "scope_targets",
    "sources",
    "user_grants",
    "user_key",
    "widens",
]

#: The switch: per-user grants count only while it is ``True``.
SETTING: Final = "KARNI_USER_GRANTS"
#: The ``origin`` of a user grant's :class:`~karni.accounts.roles.GrantSource`.
ORIGIN: Final = "user_grant"
#: The permission the admin screen and the API gate on: ``:view``, ``:add``, ...
GRANT_PERMISSION: Final = "karni_accounts.usergrant"
#: Scopes that point at rows, so a grant of them takes ``targets``.
TARGETED_SCOPES: Final[tuple[str, ...]] = ("related", "tree")

_ROWS_ATTR: Final = "_karni_user_grants"
_GRANTS_ATTR: Final = "_karni_grants"


def enabled() -> bool:
    """Experimental. Whether ``KARNI_USER_GRANTS`` is on."""
    return bool(getattr(settings, SETTING, False))


def forget(user: Any) -> None:
    """Experimental. Drop the grants cached on ``user``, so its next check reads them again."""
    if user is None:
        return
    from karni.accounts.tree_scope import CACHE_ATTR

    for name in (_GRANTS_ATTR, _ROWS_ATTR, CACHE_ATTR):
        if hasattr(user, name):
            delattr(user, name)


# checking a grant


def scope_label(kind: str, path: str = "") -> str:
    """``"all"``, ``"related:region"``: a scope as ``KARNI_ROLES`` writes it."""
    return f"{kind}:{path}" if path else kind


def normalise_targets(targets: Any) -> tuple[str, ...]:
    """Experimental. ``targets`` as text ids, in order, without repeats.

    Accepts a list (or tuple) of strings, integers or UUIDs. Raises
    :class:`~karni.exceptions.KarniValueError` (``E362``, a ``ValueError``)
    for anything else, an empty id included.
    """
    if targets is None:
        return ()
    if isinstance(targets, str | bytes) or not isinstance(targets, Iterable):
        raise _error("E362", "A user grant's targets must be a list of ids.")
    found: list[str] = []
    for target in targets:
        if isinstance(target, bool) or not isinstance(target, str | int | uuid.UUID):
            raise _error("E362", f"A user grant's target {target!r} is not an id.")
        text = str(target).strip()
        if not text:
            raise _error("E362", "A user grant's target is empty.")
        found.append(text)
    return tuple(dict.fromkeys(found))


@dataclass(frozen=True)
class Checked:
    """Experimental. A grant :func:`check` accepted: its parts and the permissions it reaches."""

    permission: str
    scope: str
    scope_path: str
    targets: tuple[str, ...]
    keys: tuple[str, ...]

    @property
    def scope_value(self) -> str:
        return scope_label(self.scope, self.scope_path)


def _error(code: str, message: str) -> KarniValueError:
    return KarniValueError(message, code=code)


def _parse_scope(scope: Any) -> tuple[str, str]:
    kind, _, path = str(scope or "").partition(":")
    if kind not in SCOPES or (kind in _PATH_SCOPES) != bool(path):
        raise _error(
            "E361",
            f"A user grant has scope {scope!r}. A scope is 'all', 'own', "
            "'related:<scope path key>', 'custom:<registered name>' or 'tree:<path to a tree "
            "model>', as in KARNI_ROLES.",
        )
    return kind, path


def _pattern_ok(permission: Any) -> bool:
    if not isinstance(permission, str) or not permission:
        return False
    if permission == "*":
        return True
    label, sep, action = permission.rpartition(":")
    return bool(sep and label and action)


def _scope_fits(model: type[models.Model], kind: str, path: str) -> bool:
    if kind == "own":
        return owner_field(model) is not None
    if kind == "related":
        return path in scope_paths(model)
    if kind == "tree":
        from karni.accounts.tree_scope import tree_path

        return tree_path(model, path) is not None
    return True


def _matching(permission: str, keys: dict[str, type[models.Model]] | None) -> list[str]:
    """The permission keys a pattern names (an explicit key resolves without the full list)."""
    if "*" not in permission:
        label, _, action = permission.rpartition(":")
        try:
            model = apps.get_model(label)
        except (LookupError, ValueError):
            return []
        if model._meta.proxy or model._meta.auto_created or action not in model_actions(model):
            return []
        return [permission_key(model, action)]
    glob = "*:*" if permission == "*" else permission
    return [
        key
        for key in (keys if keys is not None else permission_keys())
        if fnmatch.fnmatchcase(key, glob)
    ]


def _model_of(key: str, keys: dict[str, type[models.Model]] | None) -> type[models.Model]:
    if keys is not None and key in keys:
        return keys[key]
    return apps.get_model(key.rsplit(":", 1)[0])


def _bad_target(model: type[models.Model], path: str, targets: tuple[str, ...]) -> str | None:
    """The first target the scope path's field refuses, or ``None``."""
    for target in targets:
        try:
            model._base_manager.filter(**{f"{path}__in": [target]})
        except (ValueError, TypeError, ValidationError):
            return target
    return None


def check(
    permission: str,
    scope: str = "all",
    targets: Any = (),
    *,
    keys: dict[str, type[models.Model]] | None = None,
) -> Checked:
    """Experimental. Accept a grant's pattern, scope and targets, or raise why not.

    The pattern must match a permission (``E360``). The scope must be one a
    role grant takes, registered when it is ``custom:<name>``, and fit the
    models the pattern names: an explicit key whose model has no owner field
    (``own``) or no such scope path (``related:<key>``) is refused, and a
    wildcard skips those models but must keep one (``E361``). Targets must be
    ids, only for a scope in :data:`TARGETED_SCOPES`, and of the type the
    scope path's field takes (``E362``).
    """
    if not _pattern_ok(permission):
        raise _error(
            "E360",
            f"A user grant has the permission pattern {permission!r}. A pattern looks like "
            "'app_label.model:action', with '*' for either part, or '*' alone.",
        )
    kind, path = _parse_scope(scope)
    if kind == "custom" and path not in custom_scopes():
        raise _error(
            "E361",
            f"A user grant has scope 'custom:{path}', but no scope of that name is registered. "
            f"Call karni.accounts.roles.register_scope({path!r}, fn) at startup first.",
        )
    matched = _matching(permission, keys)
    if not matched:
        raise _error(
            "E360",
            f"The user grant pattern {permission!r} matches no permission. Keys look like "
            "'events.event:view', and a model's extra actions come from "
            "`class Karni: actions = [...]`.",
        )
    explicit = "*" not in permission.split(":", 1)[0] and permission != "*"
    reached: list[str] = []
    for key in matched:
        model = _model_of(key, keys)
        if _scope_fits(model, kind, path):
            reached.append(key)
        elif explicit:
            what = (
                "an owner field"
                if kind == "own"
                else f"a path {path!r} to a tree model"
                if kind == "tree"
                else f"the scope path {path!r}"
            )
            raise _error(
                "E361",
                f"The user grant {permission!r} has scope {scope_label(kind, path)!r}, but "
                f"{model.__name__} has no {what}. Declare it in `class Karni` "
                "(owner_field or scope_paths), name a relation to a tree model, or grant "
                "another scope.",
            )
    if not reached:
        raise _error(
            "E361",
            f"No permission {permission!r} matches takes scope {scope_label(kind, path)!r}: "
            "none of their models has the owner field, scope path or tree path it needs.",
        )
    found = normalise_targets(targets)
    if found and kind not in TARGETED_SCOPES:
        raise _error(
            "E362",
            f"A user grant with scope {scope_label(kind, path)!r} takes no targets: only a "
            "scope that points at rows does (related:<key>, tree:<path>).",
        )
    if found:
        for key in reached:
            model = _model_of(key, keys)
            lookup = path if kind == "tree" else scope_paths(model)[path]
            bad = _bad_target(model, lookup, found)
            if bad is not None:
                raise _error(
                    "E362",
                    f"The target {bad!r} is not a value {model.__name__}.{lookup} takes, so the "
                    f"user grant {permission!r} could never reach a row through it.",
                )
    return Checked(permission, kind, path, found, tuple(reached))


# reading grants


def live_rows(user: Any) -> list[UserGrant]:
    """Experimental. ``user``'s live grants (not deleted, not expired): one query, then cached."""
    if user is None or not getattr(user, "is_authenticated", False) or user.pk is None:
        return []
    cached = getattr(user, _ROWS_ATTR, None)
    if cached is not None:
        return list(cached)
    from karni.accounts.models import UserGrant

    rows = list(UserGrant.objects.filter(user=user).live().order_by("created_at"))
    setattr(user, _ROWS_ATTR, rows)
    return list(rows)


def _reach(row: UserGrant, keys: dict[str, type[models.Model]] | None) -> list[Grant]:
    """The grants one row gives, permission by permission. A row that no longer fits gives none."""
    try:
        kind, path = _parse_scope(row.scope)
    except KarniValueError:
        return []
    try:
        targets = normalise_targets(row.targets)
    except ValueError:
        return []
    if targets and kind not in TARGETED_SCOPES:
        return []
    if not _pattern_ok(row.permission):
        return []
    found: list[Grant] = []
    for key in _matching(row.permission, keys):
        try:
            model = _model_of(key, keys)
        except (LookupError, ValueError):
            continue
        if _scope_fits(model, kind, path):
            found.append(Grant(key, kind, path, targets=targets, grant_id=str(row.pk)))
    return found


def user_grants(user: Any) -> list[Grant]:
    """Experimental. The grants ``user``'s live user grants give, one per permission they reach.

    Each :class:`~karni.accounts.roles.Grant` carries its ``targets`` and the
    row's id (``grant_id``). Reads :func:`live_rows`, so one query per user
    instance. Does not look at the switch: :func:`~karni.accounts.roles.grants_for`
    does.
    """
    rows = live_rows(user)
    if not rows:
        return []
    keys = permission_keys() if any("*" in row.permission for row in rows) else None
    found: list[Grant] = []
    for row in rows:
        found.extend(_reach(row, keys))
    return found


def _source(row: UserGrant, key: str) -> GrantSource:
    kind, _, path = str(row.scope).partition(":")
    return GrantSource(
        key,
        "",
        "",
        kind,
        path,
        ORIGIN,
        grant_id=str(row.pk),
        reason=row.reason,
        expires_at=row.expires_at,
        targets=tuple(str(target) for target in row.targets or ()),
    )


def sources(user: Any, key: str) -> list[GrantSource]:
    """Experimental. The user grants behind ``user``'s ``key``: id, reason, expiry, targets."""
    by_id = {str(row.pk): row for row in live_rows(user)}
    seen: list[str] = []
    for grant in user_grants(user):
        if grant.permission == key and grant.grant_id not in seen:
            seen.append(grant.grant_id)
    return [_source(by_id[grant_id], key) for grant_id in seen]


@dataclass(frozen=True)
class TargetGrant:
    """Experimental. One target id a user reaches under a scope, and the grant that gives it.

    ``target`` is the id as text, ``permission`` the ``app.model:action`` the
    grant covers, and ``source`` the role or user grant
    (:class:`~karni.accounts.roles.GrantSource`: ``origin`` is ``declared`` or
    ``matrix`` for a role, ``user_grant`` with ``grant_id``, ``reason`` and
    ``expires_at`` for a user grant).
    """

    target: str
    permission: str
    source: GrantSource

    def to_dict(self) -> dict[str, Any]:
        source = self.source
        return {
            "target": self.target,
            "permission": self.permission,
            "origin": source.origin,
            "role": source.role,
            "grant": source.grant_id,
            "reason": source.reason,
            "expires_at": source.expires_at.isoformat() if source.expires_at else None,
        }


def user_key(kind: str, path: str) -> str:
    """Experimental. The user attribute a grant of ``<kind>:<path>`` without targets reaches.

    ``related:<key>`` reads ``user.<key>``. ``tree:<path>`` reads the path's
    last step: ``tree:region`` and ``tree:store__region`` both read
    ``user.region``, the node the user holds.
    """
    return path.rsplit("__", 1)[-1] if kind == "tree" else path


def _attribute_target(user: Any, path: str) -> str | None:
    """The id ``user.<path>`` holds, which a grant of ``<kind>:<path>`` without targets reaches."""
    value = getattr(user, path, None)
    if value is None:
        return None
    if isinstance(value, models.Model):
        return None if value.pk is None else str(value.pk)
    return str(value) if isinstance(value, str | int | uuid.UUID) else None


def _wanted(key: str, permission: str | None) -> bool:
    if permission is None:
        return True
    glob = "*:*" if permission == "*" else permission
    return fnmatch.fnmatchcase(key, glob)


def scope_targets(user: Any, scope: str, *, permission: str | None = None) -> list[TargetGrant]:
    """Experimental. The target ids ``user`` holds under ``scope``, and which grant gives each.

    ``scope`` is a scope that points at rows, as a grant writes it
    (``"related:region"``, ``"tree:region"``). A role grant of that scope gives
    the id ``user.<key>`` holds (for ``tree:<path>``, the path's last step,
    :func:`user_key`). A user grant gives its ``targets``, or ``user.<key>``
    when it has none (only while ``KARNI_USER_GRANTS`` is on).
    ``permission`` (a key or a ``KARNI_ROLES`` pattern) keeps only the grants
    of the permissions it matches. Expired, deleted and revoked grants give
    nothing.

    A scope that points at no row (``all``, ``own``, ``custom:<name>``)
    gives an empty list. A grant of scope ``all`` reaches every row and has
    no targets, so it is not listed: ask :func:`~karni.accounts.roles.rows_for` or
    :func:`~karni.accounts.roles.user_can` first. A superuser holds ``all``
    everywhere, so the list is empty for one. The role side costs one query
    (none when ``user.<key>`` is empty), the user side reuses the request's
    grants.
    """
    kind, path = _parse_scope(scope)
    if (
        kind not in TARGETED_SCOPES
        or user is None
        or not getattr(user, "is_authenticated", False)
        or getattr(user, "is_superuser", False)
    ):
        return []
    from karni.accounts.models import RolePermission

    found: list[TargetGrant] = []
    own_target = _attribute_target(user, user_key(kind, path)) if path else None
    rows = (
        RolePermission.objects.filter(
            role__group__in=user.groups.all(), scope=kind, scope_path=path
        )
        .exclude(scope=NONE_SCOPE)
        .select_related("role", "permission__content_type")
        .order_by("role__slug")
    )
    # A role grant reaches user.<key> alone: without it, the roles give no target.
    if own_target is not None:
        for row in rows:
            key = row.permission.key
            if not _wanted(key, permission):
                continue
            source = GrantSource(
                key, row.role.slug, row.role.name, row.scope, row.scope_path, str(row.origin)
            )
            found.append(TargetGrant(own_target, key, source))
    if enabled():
        by_id = {str(row.pk): row for row in live_rows(user)}
        for grant in user_grants(user):
            if (grant.scope, grant.scope_path) != (kind, path) or not _wanted(
                grant.permission, permission
            ):
                continue
            targets = grant.targets or ((own_target,) if own_target is not None else ())
            source = _source(by_id[grant.grant_id], grant.permission)
            found.extend(TargetGrant(target, grant.permission, source) for target in targets)
    return found


# writing grants


class GrantRefused(KarniValueError):
    """Experimental. A grant the operator may not give (``E363``). ``reasons`` says why."""

    code = "E363"

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = list(reasons)
        super().__init__("This grant is refused: " + " ".join(reasons), code="E363")


def _held_targets(operator: Any, grants: list[Grant], kind: str, path: str) -> set[str]:
    """The targets ``operator`` holds under one scope: grants' targets, or ``operator.<key>``."""
    found: set[str] = set()
    for held in grants:
        if (held.scope, held.scope_path) != (kind, path):
            continue
        if not held.targets:
            own = _attribute_target(operator, user_key(kind, path))
            if own is None:
                continue
            found.add(own)
        found.update(held.targets)
    return found


def _tree_covered(key: str, path: str, held: set[str], cache: dict[Any, set[str]]) -> set[str]:
    """The nodes under the nodes ``held`` (themselves included), as text: one walk per tree."""
    from karni.accounts.tree_scope import tree_path

    resolved = tree_path(_model_of(key, None), path)
    if resolved is None or not held:
        return set(held)
    marker = (resolved.tree_model, frozenset(held))
    if marker not in cache:
        manager = resolved.tree_model._default_manager
        from karni.accounts.tree_scope import _node_keys

        nodes = _node_keys(resolved.tree_model, held)
        found = manager.subtree_ids(nodes) if nodes else set()  # type: ignore[attr-defined]
        cache[marker] = {str(node) for node in found} | set(held)
    return cache[marker]


def refusals(operator: Any, checked: Checked) -> list[str]:
    """Experimental. Why ``operator`` may not give ``checked``: nothing for a superuser or ``None``.

    The permission matrix's rail, for one user: the operator must hold every
    permission the pattern reaches, at scope ``all`` or at the same scope.
    For a grant with targets, the operator's own targets under that scope
    (their user grants' targets, or ``operator.<key>``) must include every one.
    Under a ``tree:<path>`` scope a target below one of the operator's nodes
    counts as held: who holds a region may grant a part of it.
    """
    if operator is None or getattr(operator, "is_superuser", False):
        return []
    held = grants_for(operator)
    reasons: list[str] = []
    subtrees: dict[Any, set[str]] = {}
    for key in checked.keys:
        mine = held.get(key, [])
        if not mine:
            reasons.append(f"you do not hold {key}, so you cannot grant it.")
            continue
        if any(grant.scope == "all" for grant in mine):
            continue
        same = [g for g in mine if (g.scope, g.scope_path) == (checked.scope, checked.scope_path)]
        if not same:
            labels = sorted({scope_label(g.scope, g.scope_path) for g in mine})
            reasons.append(
                f"you hold {key} only as {', '.join(labels)}, so you cannot grant "
                f"{checked.scope_value}."
            )
            continue
        if checked.targets:
            covered = _held_targets(operator, same, checked.scope, checked.scope_path)
            if checked.scope == "tree":
                covered = _tree_covered(key, checked.scope_path, covered, subtrees)
            missing = [target for target in checked.targets if target not in covered]
            if missing:
                reasons.append(
                    f"you hold {key} as {checked.scope_value} without {', '.join(missing)}, so "
                    "you cannot grant those targets."
                )
    return reasons


def _ensure(operator: Any, checked: Checked) -> None:
    reasons = refusals(operator, checked)
    if reasons:
        raise GrantRefused(reasons)


def grant(
    operator: Any,
    user: Any,
    permission: str,
    scope: str = "all",
    *,
    targets: Any = (),
    expires_at: Any = None,
    reason: str = "",
) -> UserGrant:
    """Experimental. Give ``user`` one grant, checked (``E360`` to ``E362``) and allowed (``E363``).

    ``operator`` becomes ``granted_by`` and the actor of the history entry.
    """
    return bulk_grant(
        operator,
        [user],
        permission,
        scope,
        targets=targets,
        expires_at=expires_at,
        reason=reason,
    )[0]


def bulk_grant(
    operator: Any,
    users: Iterable[Any],
    permission: str,
    scope: str = "all",
    *,
    targets: Any = (),
    expires_at: Any = None,
    reason: str = "",
) -> list[UserGrant]:
    """Experimental. Give every user in ``users`` the same grant: all of them or none.

    One check and one refusal test for the whole batch, then one row (and one
    history entry) per user, in one transaction.
    """
    from karni.accounts.models import UserGrant

    checked = check(permission, scope, targets)
    _ensure(operator, checked)
    people = list(users)
    created: list[UserGrant] = []
    with transaction.atomic(), current_user(operator):
        for person in people:
            created.append(
                UserGrant.objects.create(
                    user=person,
                    permission=checked.permission,
                    scope=checked.scope_value,
                    targets=list(checked.targets),
                    expires_at=expires_at,
                    granted_by=operator,
                    reason=reason or "",
                )
            )
    for person in people:
        forget(person)
    return created


#: The fields :func:`change` may set.
CHANGEABLE: Final = ("permission", "scope", "targets", "expires_at", "reason")


def widens(row: UserGrant, fields: dict[str, Any]) -> bool:
    """Experimental. Whether setting ``fields`` on ``row`` gives more than it gives now.

    Another permission, scope or targets, or a later expiry (or none) gives
    more. An earlier expiry and a new reason do not.
    """
    if any(name in fields for name in ("permission", "scope", "targets")):
        return True
    if "expires_at" in fields:
        after = fields["expires_at"]
        return after is None or (row.expires_at is not None and after > row.expires_at)
    return False


def change(operator: Any, row: UserGrant, **fields: Any) -> UserGrant:
    """Experimental. Change a grant's permission, scope, targets, expiry or reason.

    A change that gives more (another permission, scope or targets, a later
    expiry or none) is checked and refused like a new grant, and makes the
    operator ``granted_by``. Expiring sooner and a new reason are not.
    """
    unknown = sorted(set(fields) - set(CHANGEABLE))
    if unknown:
        raise KarniTypeError(
            f"change() cannot set {', '.join(unknown)}. It sets {', '.join(CHANGEABLE)}.",
            code="E365",
        )
    if widens(row, fields):
        checked = check(
            fields.get("permission", row.permission),
            fields.get("scope", row.scope),
            fields.get("targets", row.targets),
        )
        _ensure(operator, checked)
        fields = {
            **fields,
            "permission": checked.permission,
            "scope": checked.scope_value,
            "targets": list(checked.targets),
        }
        row.granted_by = operator
    for name, value in fields.items():
        setattr(row, name, value)
    with current_user(operator):
        row.save()
    _forget_grantee(row)
    return row


def expire(operator: Any, row: UserGrant, at: Any = None) -> UserGrant:
    """Experimental. End a grant at ``at`` (default now). The row and its history stay."""
    from django.utils import timezone

    return change(operator, row, expires_at=at if at is not None else timezone.now())


def revoke(operator: Any, row: UserGrant) -> None:
    """Experimental. Delete a grant: a soft delete, recorded with ``operator`` as the actor."""
    with current_user(operator):
        row.delete()
    _forget_grantee(row)


def _forget_grantee(row: UserGrant) -> None:
    """Forget the grantee's cached grants when the row holds the instance (no query)."""
    if type(row).user.is_cached(row):
        forget(row.user)
