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

from django.contrib.auth import get_user_model
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db.models import Model, Q, QuerySet

from karni.api.access import (
    Access,
    Authenticated,
    Can,
    Explained,
    Granted,
    HasRole,
    Owned,
    Public,
    Where,
    owner_fields,
)
from karni.meta import karni_option, owner_field, scope_paths
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
    "NearMiss",
    "explain_leaves",
    "grant_lines",
    "holders",
    "leaf_location",
    "near_misses",
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
        return f"needs one of {needs}, but holds {held}"
    if isinstance(predicate, Can):
        key = predicate.keys[0]
        if not signed_in:
            return f"not signed in: anonymous holds no grant for {key}"
        info = facts.get("permissions", {}).get(key, {})
        granted = [s for s in info.get("sources", []) if s.scope != "none"]
        if allows:
            via = ", ".join(_source_name(s) for s in granted) or "a grant"
            return f"holds {key} through {via}"
        return f"no {_grantors()} you hold grants {key}"
    if isinstance(predicate, Where):
        if explained.rows is True or explained.rows is False:
            return f"the function returned {explained.rows}"
        return "returns a row filter, so the gate passes and the rows decide"
    return "passes" if allows else "refuses"


def _source_name(source: Any) -> str:
    if source.origin == "superuser":
        return "superuser"
    if source.origin == USER_GRANT:
        return f"user grant {source.grant_id} (scope {source.scope_label}{_targets(source)})"
    return f"role {source.role!r} (scope {source.scope_label})"


#: The ``origin`` of a per-user grant's source (``karni.accounts.grants.ORIGIN``).
USER_GRANT = "user_grant"


def _user_grants_on() -> bool:
    from karni.accounts.grants import enabled

    return enabled()


def _grantors() -> str:
    """What may grant a permission: roles, and user grants while they are on."""
    return "role or user grant" if _user_grants_on() else "role"


def _targets(source: Any) -> str:
    targets = tuple(getattr(source, "targets", ()) or ())
    if not targets:
        return ""
    shown = ", ".join(targets[:5]) + (f" and {len(targets) - 5} more" if len(targets) > 5 else "")
    return f" on {shown}"


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
        return [f"the row must match {q_text(leaf.rows, you=user)}{where}, but it has {has}"]
    return []


# near misses


@dataclass(frozen=True)
class NearMiss:
    """A user field beside an ``Owned`` path's last hop that does match rows for the user.

    ``owners`` names who calls that field the model's owner: the routed
    viewsets whose ``access`` owns the model through it, and
    ``Karni.owner_field`` when declared.
    """

    written: str
    path: str
    count: int
    model: str
    field: str
    owners: tuple[str, ...]

    @property
    def text(self) -> str:
        why = f": {', '.join(self.owners)} owns {self.model} through {self.field}"
        return (
            f"Owned({self.path!r}) would match {self.count} row(s) where "
            f"{self.written} matches none{why if self.owners else ''}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "predicate": self.written,
            "instead": f"Owned({self.path!r})",
            "rows_count": self.count,
            "owners": list(self.owners),
        }


def _owners_of(model: type[Model]) -> dict[str, list[str]]:
    """Field name → who owns ``model`` through it (routed viewsets, ``Karni.owner_field``)."""
    from karni.why.resolve import resources

    found: dict[str, list[str]] = {}
    declared = karni_option(model, "owner_field")
    if declared:
        found.setdefault(str(declared), []).append(f"{model.__name__}.Karni.owner_field")
    for resource in resources():
        viewset = resource.viewset
        if (
            getattr(viewset, "model", None) is not model
            and getattr(getattr(viewset, "queryset", None), "model", None) is not model
        ):
            continue
        access = getattr(viewset, "access", None)
        if isinstance(access, Granted):  # as BaseViewSet.get_access normalises it
            access = Access(read=access, write=access)
        for name in owner_fields(access, model):
            label = f"{viewset.__name__}.access"
            if label not in found.setdefault(name, []):
                found[name].append(label)
    return found


def near_misses(
    predicate: Any, *, user: Any, model: type[Model], base: QuerySet[Any]
) -> list[NearMiss]:
    """Other user fields an ``Owned`` that matches nothing could have meant.

    ``Owned("event__created_by")`` matching no booking while the user is the
    ``organizer`` of their events is the common slip: the path walks to the
    audit stamp, not the owner. Each other foreign key to the user model on
    the model the path ends at is tried against ``base``; those that match
    rows come back, fields a viewset owns the model through first.
    """
    if not isinstance(predicate, Owned) or not getattr(user, "is_authenticated", False):
        return []
    prefix, _, last = predicate.path.rpartition("__")
    target: Any = model
    try:
        for part in filter(None, prefix.split("__")):
            target = target._meta.get_field(part).related_model
    except FieldDoesNotExist:
        return []
    if target is None:
        return []
    user_model = get_user_model()
    owners = _owners_of(target)
    found: list[NearMiss] = []
    for field in target._meta.get_fields():
        if field.name == last or not field.concrete or not field.is_relation:
            continue
        if field.related_model is not user_model or field.many_to_many:
            continue
        path = f"{prefix}__{field.name}" if prefix else field.name
        count = base.filter(**{path: user}).distinct().count()
        if count:
            found.append(
                NearMiss(
                    written=predicate_text(predicate),
                    path=path,
                    count=count,
                    model=target.__name__,
                    field=field.name,
                    owners=tuple(owners.get(field.name, ())),
                )
            )
    found.sort(key=lambda miss: (not miss.owners, -miss.count))
    return found


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
        if _user_grants_on():
            fixes.append(
                f"give {who} a user grant of {key!r}: karni.accounts.grants.grant(...) or the "
                "admin's user grants"
            )
        return fixes
    if row is None or leaf.allows is False:
        return []
    # (rank, text): a user grant to widen first, then a change to this row's
    # scope, then a role at scope 'all'. Only the first two are printed.
    ranked: list[tuple[int, str]] = []
    tree_grants: dict[str, list[str]] = {}
    tree_roles: list[str] = []
    for source in sources:
        if source.scope == "own":
            owner = owner_field(model)
            if owner:
                now = row_value(row, owner, you=user)
                ranked.append((1, f"make {who} the row's {owner} (now {now}) for the 'own' scope"))
        elif source.scope == "related" and source.origin == USER_GRANT and source.targets:
            path = scope_paths(model).get(source.scope_path, source.scope_path)
            ranked.append(
                (
                    0,
                    f"add the row's {path} ({row_value(row, path, you=user)}) to the targets of "
                    f"user grant {source.grant_id}",
                )
            )
        elif source.scope == "related":
            path = scope_paths(model).get(source.scope_path, source.scope_path)
            ranked.append(
                (
                    1,
                    f"set {who}.{source.scope_path} to the row's {path} "
                    f"({row_value(row, path, you=user)}) for the 'related:{source.scope_path}' "
                    "scope",
                )
            )
        elif source.scope == "tree" and source.origin == USER_GRANT:
            tree_grants.setdefault(source.scope_path, []).append(source.grant_id)
        elif source.scope == "tree" and source.scope_path not in tree_roles:
            tree_roles.append(source.scope_path)
        if source.role:
            role_where = settings_location("KARNI_ROLES", f'"{source.role}"')
            at = f" ({role_where})" if role_where else ""
            ranked.append(
                (2, f"grant role {source.role!r} {key!r} at scope 'all' in KARNI_ROLES{at}")
            )
    ranked += _tree_fixes(key, tree_grants, tree_roles, user=user, model=model, row=row)
    return [text for _rank, text in sorted(ranked, key=lambda fix: fix[0])]


def _tree_fixes(
    key: str,
    granted: dict[str, list[str]],
    roles: list[str],
    *,
    user: Any,
    model: type[Model],
    row: Model,
) -> list[tuple[int, str]]:
    """How a tree grant would reach ``row``: widen a user grant, set the attribute, or add a grant.

    A role grant reads the node in ``user.<last step>``. When the user model
    has no such attribute (karni.W620), the fix is a user grant, never the
    attribute.
    """
    from karni.accounts.grants import user_key

    who = display_user(user)
    fixes: list[tuple[int, str]] = []
    for path, ids in granted.items():
        value = row_value(row, path, you=user)
        node = _row_node(model, row, path)
        more = f" (or of {', '.join(ids[1:])})" if len(ids) > 1 else ""
        fixes.append(
            (
                0,
                f"add the row's {path} ({value}) or a node above it to the targets of user grant "
                f"{ids[0]}{more}: karni.accounts.grants.change(operator, grant, "
                f"targets=[*grant.targets, {node!r}]), or the admin's user grants",
            )
        )
    for path in roles:
        if path in granted:
            continue  # widening the user grant above is the fix
        attribute = user_key("tree", path)
        value = row_value(row, path, you=user)
        if hasattr(user, attribute):
            fixes.append(
                (
                    1,
                    f"set {who}.{attribute} to the row's {path} ({value}) or a node above it for "
                    f"the 'tree:{path}' scope",
                )
            )
        elif _user_grants_on():
            node = _row_node(model, row, path)
            fixes.append(
                (
                    1,
                    f"give {who} a user grant of {key!r} at scope 'tree:{path}' on the row's "
                    f"{path} ({value}) or a node above it: karni.accounts.grants.grant(operator, "
                    f"user, {key!r}, 'tree:{path}', targets=[{node!r}]), or the admin's user "
                    "grants",
                )
            )
        else:
            fixes.append(
                (
                    1,
                    f"give {type(user).__name__} a {attribute!r} attribute holding a node (a field "
                    "or a property), or set KARNI_USER_GRANTS = True and give "
                    f"{who} a user grant of {key!r} at scope 'tree:{path}'",
                )
            )
    return fixes


def _row_node(model: type[Model], row: Model, path: str) -> str:
    """The id of the tree node ``row`` carries on ``path``, as text (the first when many)."""
    found = (
        model._base_manager.filter(pk=row.pk)
        .exclude(**{f"{path}__isnull": True})
        .values_list(path, flat=True)
        .first()
    )
    return "<node id>" if found is None else str(found)


# grants


@dataclass
class GrantLine:
    """One permission a ``Can``/``Granted`` leaf asked about, and every role behind it."""

    key: str
    text: list[str]
    data: dict[str, Any]


def _grant_rows(source: Any, rows_by_grant: list[tuple[Any, Any]]) -> Any:
    """The rows the grant behind ``source`` reaches: a user grant by id, a role by scope."""
    for grant, rows in rows_by_grant:
        grant_id = getattr(grant, "grant_id", "")
        if source.origin == USER_GRANT:
            if grant_id == source.grant_id:
                return rows
        elif not grant_id and (grant.scope, grant.scope_path) == (source.scope, source.scope_path):
            return rows
    return False


def _given(source: Any, user: Any) -> str:
    """``user grant 12`` or ``role 'manager' (through you.region)``: who gives the nodes."""
    if source.origin == USER_GRANT:
        return f"user grant {source.grant_id}"
    from karni.accounts.grants import user_key

    attribute = user_key("tree", source.scope_path)
    lacks = "" if hasattr(user, attribute) else f", which {type(user).__name__} does not have"
    return f"role {source.role!r} (through {display_user(user)}.{attribute}{lacks})"


def _tree_line(
    source: Any, key: str, *, user: Any, model: type[Model], row: Model | None
) -> tuple[str, dict[str, Any]]:
    """The nodes behind a tree grant, in words, and for a row the granted node it is under."""
    from karni.accounts.tree_scope import explain_row, source_nodes, tree_path

    path = source.scope_path
    if tree_path(model, path) is None:
        return f"tree:{path} does not resolve on {model.__name__}", {"path": path}
    verdict = explain_row(model, path, row, source_nodes(user, path, key, source))
    return verdict.text(_given(source, user)), verdict.to_dict()


def grant_lines(
    leaf: Explained, *, user: Any, model: type[Model], row: Model | None = None
) -> list[GrantLine]:
    """The grants a ``Can`` leaf consulted: per role or user grant, scope and the rows it reaches.

    With ``row``, each grant also says whether it reaches that row, so the
    grant that decided is named.
    """
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
            held = f" (roles that hold it: {', '.join(others)})" if others else ""
            text.append(f"{key}  none: no {_grantors()} you hold grants it{held}")
        for source in sources:
            rows = _grant_rows(source, rows_by_grant)
            origin = _origin_text(source)
            reaches = _matches(None, row, rows) if source.scope != "none" else None
            mark = "  ← reaches this row" if reaches else ""
            if source.scope == "none":
                text.append(f"{key}  role {source.role!r}: revoked in the permission matrix")
            else:
                text.append(
                    f"{key}  scope {source.scope_label}{_targets(source)}  {origin}  → "
                    f"{q_text(rows, you=user)}{mark}"
                )
            tree: dict[str, Any] | None = None
            if source.scope == "tree":
                said, tree = _tree_line(source, key, user=user, model=model, row=row)
                text.append(f"    {said}")
            entry: dict[str, Any] = {
                "permission": key,
                "role": source.role,
                "scope": source.scope_label,
                "origin": source.origin,
                "rows": q_text(rows, you=user),
            }
            if row is not None:
                entry["reaches_row"] = bool(reaches)
            if source.origin == USER_GRANT:
                entry["grant"] = source.grant_id
                entry["reason"] = source.reason
                entry["expires_at"] = source.expires_at.isoformat() if source.expires_at else None
                entry["targets"] = list(source.targets)
            if tree is not None:
                entry["tree"] = tree
            entries.append(entry)
        found.append(GrantLine(key, text, {"permission": key, "grants": entries}))
    return found


def _origin_text(source: Any) -> str:
    if source.origin == "superuser":
        return "(superuser: every permission at scope all)"
    if source.origin == USER_GRANT:
        parts = [f"user grant {source.grant_id}"]
        if source.reason:
            parts.append(f"reason {source.reason!r}")
        parts.append(
            f"expires {source.expires_at:%Y-%m-%d %H:%M}" if source.expires_at else "no expiry"
        )
        return f"({', '.join(parts)})"
    if source.origin == "matrix":
        return f"(role {source.role!r}, set in the permission matrix)"
    location = settings_location("KARNI_ROLES", f'"{source.role}"')
    where = f", {location}" if location else ""
    return f"(role {source.role!r}, KARNI_ROLES{where})"


def is_q(rows: Any) -> bool:
    return isinstance(rows, Q)
