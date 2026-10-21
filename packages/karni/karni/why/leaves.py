"""Words for one predicate's answer: what it needs, what this request has, and how to change it.

Every input here is an :class:`~karni.api.access.Explained` — the predicate's
own ``allows()``/``rows()`` for the request, plus the facts it read — and the
row filter ``rows`` is applied to the row with the same
:func:`karni.rows.apply_rows` the read pipeline uses. Nothing here decides;
it puts the access layer's decisions into sentences.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ValidationError
from django.db.models import Model, Q, QuerySet

from karni.api.access import Authenticated, Can, Explained, HasRole, Owned, Public, Where
from karni.meta import owner_field, scope_paths
from karni.rows import apply_rows
from karni.why.source import (
    Location,
    callable_location,
    class_location,
    display_user,
    q_paths,
    q_text,
    row_value,
    settings_location,
)

__all__ = [
    "GrantLine",
    "Leaf",
    "explain_leaves",
    "grant_lines",
    "holders",
    "leaf_location",
    "predicate_text",
]


def predicate_text(predicate: Any) -> str:
    """The predicate as written (``Where(<lambda>)`` for a lambda)."""
    text = repr(predicate)
    return text.replace("Where(lambda)", "Where(<lambda>)")


def leaf_location(predicate: Any) -> Location | None:
    """Where a leaf is defined: a ``Where`` function's own line, else the predicate class."""
    if isinstance(predicate, Where):
        return callable_location(predicate.fn)
    return class_location(type(predicate))


@dataclass
class Leaf:
    """One leaf of a predicate, judged for the request and (optionally) one row."""

    explained: Explained
    gate: str
    rows_text: str
    matches_row: bool | None
    row_values: dict[str, str]
    location: Location | None
    fixes: list[str]

    @property
    def predicate(self) -> Any:
        return self.explained.predicate

    def as_dict(self) -> dict[str, Any]:
        return {
            "predicate": predicate_text(self.predicate),
            "allows": self.explained.allows,
            "gate": self.gate,
            "rows": self.rows_text,
            "matches_row": self.matches_row,
            "row_values": self.row_values,
            "where": self.location.as_dict() if self.location else None,
        }


def _gate_text(explained: Explained, user: Any) -> str:
    """Why the leaf's request-level answer is what it is."""
    predicate = explained.predicate
    facts = explained.facts
    allows = explained.allows
    signed_in = bool(getattr(user, "is_authenticated", False))
    if isinstance(predicate, Public):
        return "everyone passes"
    if isinstance(predicate, Authenticated):
        return "signed in" if allows else "not signed in"
    if isinstance(predicate, Owned):
        if allows:
            return "signed in (the row decides)"
        return "not signed in"
    if isinstance(predicate, HasRole):
        held = ", ".join(facts.get("held", ())) or "no role"
        needs = ", ".join(predicate.names)
        if allows:
            return f"holds {', '.join(set(predicate.names) & set(facts.get('held', ())))}"
        return f"needs one of {needs}; holds {held}"
    if isinstance(predicate, Can):
        key = predicate.keys[0]
        if not signed_in:
            return f"not signed in: anonymous holds no grant for {key}"
        info = facts.get("permissions", {}).get(key, {})
        granted = [s for s in info.get("sources", []) if s.scope != "none"]
        if allows:
            via = ", ".join(_source_name(s) for s in granted) or "a grant"
            return f"holds {key} through {via}"
        return f"no role you hold grants {key}"
    if isinstance(predicate, Where):
        if explained.rows is True or explained.rows is False:
            return f"the function returned {explained.rows}"
        return "returns a row filter, so the gate passes and the rows decide"
    return "passes" if allows else "refuses"


def _source_name(source: Any) -> str:
    if source.origin == "superuser":
        return "superuser"
    return f"role {source.role!r} (scope {source.scope_label})"


def _matches(base: QuerySet[Any] | None, row: Model | None, rows: Any) -> bool | None:
    if row is None:
        return None
    if rows is True:
        return True
    if rows is False:
        return False
    if base is None:
        base = type(row)._default_manager.all()
    try:
        return bool(apply_rows(base.filter(pk=row.pk), rows).exists())
    except (ValidationError, ValueError, TypeError):
        return False


def explain_leaves(
    explained: Explained,
    *,
    user: Any,
    model: type[Model],
    row: Model | None = None,
    base: QuerySet[Any] | None = None,
) -> list[Leaf]:
    """Every leaf of ``explained``, judged for the request and ``row``."""
    found: list[Leaf] = []
    for leaf in explained.leaves():
        rows = leaf.rows
        values: dict[str, str] = {}
        if row is not None:
            for path in q_paths(rows):
                values[path] = row_value(row, path, you=user)
        found.append(
            Leaf(
                explained=leaf,
                gate=_gate_text(leaf, user),
                rows_text=_rows_text(leaf, user),
                matches_row=_matches(base, row, rows),
                row_values=values,
                location=leaf_location(leaf.predicate),
                fixes=_fixes(leaf, user=user, model=model, row=row, values=values),
            )
        )
    return found


def _rows_text(leaf: Explained, user: Any) -> str:
    predicate = leaf.predicate
    if isinstance(predicate, HasRole) and leaf.rows is False:
        return "no row (role not held)"
    if isinstance(predicate, Can) and leaf.rows is False:
        if not getattr(user, "is_authenticated", False):
            return "no row (not signed in)"
        return "no row (no grant)"
    if isinstance(predicate, Owned | Authenticated) and leaf.rows is False:
        return "no row (not signed in)"
    return q_text(leaf.rows, you=user)


# fixes


def holders(key: str) -> list[str]:
    """Role slugs whose grants include ``key`` (revoked cells excluded)."""
    from karni.accounts.models import RolePermission
    from karni.accounts.roles import NONE_SCOPE

    label, _, action = key.rpartition(":")
    app_label, _, model_name = label.partition(".")
    rows = (
        RolePermission.objects.filter(
            permission__content_type__app_label=app_label,
            permission__content_type__model=model_name,
            permission__action=action,
        )
        .exclude(scope=NONE_SCOPE)
        .values_list("role__slug", flat=True)
        .order_by("role__slug")
    )
    from karni.accounts.roles import declared_roles

    declared = [spec.slug for spec in declared_roles()]
    found = list(dict.fromkeys(rows))
    # Roles the declaration names first: an undeclared role is a leftover in the database.
    return sorted(found, key=lambda slug: (slug not in declared, slug))


def _roles_of(user: Any) -> list[str]:
    from karni.accounts.permissions import user_roles

    return user_roles(user)


def _fixes(
    leaf: Explained,
    *,
    user: Any,
    model: type[Model],
    row: Model | None,
    values: dict[str, str],
) -> list[str]:
    """Concrete changes that would make this leaf say yes (for this row, when given)."""
    predicate = leaf.predicate
    who = display_user(user)
    signed_in = bool(getattr(user, "is_authenticated", False))
    if isinstance(predicate, Public):
        return []
    if not signed_in and isinstance(predicate, Authenticated | Owned | Can | HasRole):
        return [f"sign in: {predicate_text(predicate)} admits only signed-in users"]
    if isinstance(predicate, Authenticated):
        return []
    if isinstance(predicate, HasRole):
        if leaf.allows:
            return []
        names = predicate.names
        role = names[0]
        more = f" (or one of {', '.join(names[1:])})" if len(names) > 1 else ""
        return [f"give {who} the role {role!r}{more}: assign_role(user, {role!r}) or the admin"]
    if isinstance(predicate, Owned):
        if row is None:
            return [f"rows appear once {who} is the {predicate.path} of some {model.__name__}"]
        now = values.get(predicate.path) or row_value(row, predicate.path, you=user)
        return [f"make {who} the row's {predicate.path} (now {now})"]
    if isinstance(predicate, Can):
        return _can_fixes(leaf, user=user, model=model, row=row)
    if isinstance(predicate, Where):
        location = leaf_location(predicate)
        where = f" ({location})" if location else ""
        if leaf.rows is False:
            return [f"Where {predicate_text(predicate)}{where} returns False for this request"]
        if row is None:
            return [f"rows appear once some row matches {q_text(leaf.rows, you=user)}{where}"]
        has = ", ".join(f"{path}={value}" for path, value in values.items())
        return [f"the row must match {q_text(leaf.rows, you=user)}{where}; it has {has}"]
    return []


def _can_fixes(leaf: Explained, *, user: Any, model: type[Model], row: Model | None) -> list[str]:
    predicate = leaf.predicate
    if not isinstance(predicate, Can):
        return []
    key = predicate.keys[0]
    who = display_user(user)
    info = leaf.facts.get("permissions", {}).get(key, {})
    sources = [s for s in info.get("sources", []) if s.scope != "none"]
    roles = _roles_of(user)
    location = settings_location("KARNI_ROLES")
    where = f" ({location})" if location else ""
    if not sources:
        fixes = []
        if roles:
            fixes.append(
                f"grant {key!r} to role {roles[0]!r} in KARNI_ROLES{where}, then karni sync-roles"
            )
        others = [slug for slug in holders(key) if slug not in roles]
        if others:
            fixes.append(f"give {who} the role {others[0]!r}, which holds {key!r}")
        elif not roles:
            fixes.append(f"give {who} a role and grant it {key!r} in KARNI_ROLES{where}")
        return fixes
    if row is None or leaf.allows is False:
        return []
    fixes = []
    for source in sources:
        if source.scope == "own":
            owner = owner_field(model)
            if owner:
                now = row_value(row, owner, you=user)
                fixes.append(f"make {who} the row's {owner} (now {now}) — the 'own' scope")
        elif source.scope == "related":
            path = scope_paths(model).get(source.scope_path, source.scope_path)
            fixes.append(
                f"set {who}.{source.scope_path} to the row's {path} "
                f"({row_value(row, path, you=user)}) — the 'related:{source.scope_path}' scope"
            )
        if source.role:
            role_where = settings_location("KARNI_ROLES", f'"{source.role}"')
            at = f" ({role_where})" if role_where else ""
            fixes.append(f"grant role {source.role!r} {key!r} at scope 'all' in KARNI_ROLES{at}")
    return fixes


# grants


@dataclass
class GrantLine:
    """One permission a ``Can``/``Granted`` leaf asked about, and every role behind it."""

    key: str
    text: list[str]
    data: dict[str, Any]


def grant_lines(leaf: Explained, *, user: Any, model: type[Model]) -> list[GrantLine]:
    """The grants a ``Can`` leaf consulted: per role, scope, origin and the rows it reaches."""
    predicate = leaf.predicate
    if not isinstance(predicate, Can):
        return []
    found: list[GrantLine] = []
    for key in predicate.keys:
        info = leaf.facts.get("permissions", {}).get(key, {})
        sources = list(info.get("sources", []))
        rows_by_grant = list(info.get("grants", []))
        text: list[str] = []
        entries: list[dict[str, Any]] = []
        if not getattr(user, "is_authenticated", False):
            text.append(f"{key}  none: anonymous holds no grant")
        elif not sources:
            others = holders(key)
            held = f"; roles that hold it: {', '.join(others)}" if others else ""
            text.append(f"{key}  none: no role you hold grants it{held}")
        for source in sources:
            rows = next(
                (
                    r
                    for grant, r in rows_by_grant
                    if grant.scope == source.scope and grant.scope_path == source.scope_path
                ),
                False,
            )
            origin = _origin_text(source)
            if source.scope == "none":
                text.append(f"{key}  role {source.role!r}: revoked in the permission matrix")
            else:
                text.append(
                    f"{key}  scope {source.scope_label}  {origin}  → {q_text(rows, you=user)}"
                )
            entries.append(
                {
                    "permission": key,
                    "role": source.role,
                    "scope": source.scope_label,
                    "origin": source.origin,
                    "rows": q_text(rows, you=user),
                }
            )
        found.append(GrantLine(key, text, {"permission": key, "grants": entries}))
    return found


def _origin_text(source: Any) -> str:
    if source.origin == "superuser":
        return "(superuser: every permission at scope all)"
    if source.origin == "matrix":
        return f"(role {source.role!r}, set in the permission matrix)"
    location = settings_location("KARNI_ROLES", f'"{source.role}"')
    where = f", {location}" if location else ""
    return f"(role {source.role!r}, KARNI_ROLES{where})"


def is_q(rows: Any) -> bool:
    return isinstance(rows, Q)
