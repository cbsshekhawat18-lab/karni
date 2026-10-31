"""Experimental. The ``tree:<path>`` scope: a grant on a node reaches every row under it.

A large app grants nodes of a hierarchy (a region, a product category), and a
user then sees every row tagged with one of those nodes or with any node below
them. ``tree:<path>`` is that scope. ``<path>`` is the row's foreign key or
many-to-many to a :class:`karni.models.TreeModel`, through relations when
needed: ``tree:region``, ``tree:product__categories``. It works wherever a
scope does: ``KARNI_ROLES`` grants, per-user grants, ``Granted()``, ``Can``,
``user.can``, the admin's row scope, imports and exports, and
``Where(tree_scope(Order, "region"))`` in an ``Access`` declaration. A path
that does not end at a tree model is an error at startup (``E490``).

The nodes come from :func:`karni.accounts.grants.scope_targets`: a user grant
gives its ``targets``, and a role grant (or a user grant without targets)
gives the node the user holds in the attribute named after the path's last
step (``tree:product__category`` reads ``user.category``). No node, no row: a
tree grant never reaches every row.

The rows compile to one subquery: the rows whose path value is in the subtree
of any granted node, through the cycle-safe recursive walk of
:mod:`karni.tree`, started from every granted node at once. The nodes are read
once per request (cached on the user, as the grants are) and the walk runs
inside the statement that reads the rows, so the scope adds no query per row
and none per node. The walk follows the live nodes: a soft-deleted node hides
its branch from the scope, as it does from the tree endpoints.

Also here: :func:`access_forest`, the user's granted nodes with their
ancestors and every root (the ``access/`` endpoint of a tree resource), and
:func:`explain_row`, which node let a row in (``karni why``).

Override / escape hatch: :func:`subtree_rows` builds the row filter for any
nodes, :class:`SubtreeKeys` is the subquery alone, and a ``custom:<name>``
scope (:func:`karni.accounts.roles.register_scope`) stays available for a
rule the tree scope does not express.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from django.core.exceptions import EmptyResultSet, FieldDoesNotExist, ValidationError
from django.db import models
from django.db.models import Exists, OuterRef, Q
from django.db.models.constants import LOOKUP_SEP
from django.db.models.expressions import Expression

from karni.exceptions import KarniImproperlyConfigured

if TYPE_CHECKING:
    from django.db.backends.base.base import BaseDatabaseWrapper
    from django.db.models.sql.compiler import SQLCompiler

    from karni.accounts.grants import TargetGrant
    from karni.accounts.roles import Grant, GrantSource

__all__ = [
    "KIND",
    "Forest",
    "ForestNode",
    "RowVerdict",
    "SubtreeKeys",
    "TreePath",
    "access_forest",
    "explain_row",
    "grant_nodes",
    "granted_targets",
    "resolve_path",
    "source_nodes",
    "subtree_rows",
    "tree_path",
    "tree_rows",
    "tree_scope",
]

#: The scope's kind, as ``KARNI_ROLES`` writes it before the colon.
KIND: Final = "tree"

#: The granted nodes, cached on the user per (path, permission) for the request.
CACHE_ATTR: Final = "_karni_tree_targets"

#: How many node labels a sentence names before it says "and N more".
_SHOWN: Final = 5


# the path


@dataclass(frozen=True)
class TreePath:
    """Experimental. A ``tree:<path>`` resolved on a model: the tree it ends at.

    ``to_many`` is true when a step of the path is a many-to-many or a reverse
    relation, so a row can carry several nodes (the row filter then reads
    each row once, :func:`karni.rows.apply_rows`).
    """

    model: type[models.Model]
    path: str
    tree_model: type[models.Model]
    to_many: bool

    @property
    def scope(self) -> str:
        return f"{KIND}:{self.path}"


_RESOLVED: dict[tuple[type[models.Model], str], TreePath] = {}


def _refuse(model: type[models.Model], path: str, why: str) -> KarniImproperlyConfigured:
    return KarniImproperlyConfigured(
        f"The scope 'tree:{path}' on {model.__name__}: {why} The path names the row's foreign "
        "key or many-to-many to a tree model (a model on karni.models.TreeModel), through "
        "relations when needed, e.g. tree:region or tree:product__categories.",
        code="E490",
    )


def resolve_path(model: type[models.Model], path: str) -> TreePath:
    """Experimental. ``tree:<path>`` on ``model``, or ``E490`` when it does not end at a tree.

    Each step of ``path`` is a relation of the model before it (a foreign
    key, a one-to-one, a many-to-many or a reverse relation), and the last one
    points at a :class:`karni.models.TreeModel`. Cached per model and path.
    """
    from karni.tree import is_tree_model

    cached = _RESOLVED.get((model, path))
    if cached is not None:
        return cached
    segments = str(path or "").split(LOOKUP_SEP)
    if not path or not all(segments):
        raise _refuse(model, str(path), "the path is empty or has an empty step.")
    current: type[models.Model] = model
    to_many = False
    for segment in segments:
        try:
            found = current._meta.get_field(segment)
        except FieldDoesNotExist:
            raise _refuse(
                model, path, f"{segment!r} is not a field of {current.__name__}."
            ) from None
        related = getattr(found, "related_model", None)
        if not found.is_relation or not isinstance(related, type):
            raise _refuse(
                model, path, f"{current.__name__}.{segment} is not a relation to another model."
            )
        if found.many_to_many or found.one_to_many:
            to_many = True
        current = related
    if not is_tree_model(current):
        raise _refuse(model, path, f"it ends at {current.__name__}, which is not a tree model.")
    resolved = TreePath(model, path, current, to_many)
    _RESOLVED[(model, path)] = resolved
    return resolved


def tree_path(model: type[models.Model], path: str) -> TreePath | None:
    """Experimental. :func:`resolve_path`, or ``None`` when the path does not end at a tree."""
    try:
        return resolve_path(model, path)
    except KarniImproperlyConfigured:
        return None


# the subquery


def _node_keys(tree_model: type[models.Model], nodes: Iterable[Any]) -> list[Any]:
    """The nodes as keys of ``tree_model``, in order and once each; an invalid id is skipped.

    A grant's targets are text and may outlive a key type change or hold a
    typo the checks did not see (a row saved directly). Such a target names
    no node, so it reaches no row instead of failing the request.
    """
    from karni.tree import pk_field

    pk = pk_field(tree_model)
    found: list[Any] = []
    for node in nodes:
        value = node.pk if isinstance(node, models.Model) else node
        if value is None or value == "":
            continue
        try:
            key = pk.to_python(value)
        except (ValidationError, TypeError, ValueError):
            continue
        if key is not None and key not in found:
            found.append(key)
    return found


class SubtreeKeys(Expression):
    """Experimental. The keys of every live node in the subtrees under ``nodes``: one subquery.

    ``Q(region__in=SubtreeKeys(Region, [europe.pk, asia.pk]))`` reads the rows
    whose region is Europe, Asia or a node below either. The SQL is the walk
    of :func:`karni.tree.walk_sql` for the database the query runs on,
    started from every node at once and restricted to the rows of the tree
    model's default manager (the live nodes).
    """

    contains_aggregate = False
    contains_over_clause = False

    def __init__(self, tree_model: type[models.Model], nodes: Sequence[Any]) -> None:
        super().__init__(output_field=models.Field())
        self.tree_model = tree_model
        self.nodes = tuple(nodes)

    def as_sql(  # type: ignore[override]
        self, compiler: SQLCompiler, connection: BaseDatabaseWrapper
    ) -> tuple[str, list[Any]]:
        from karni.tree import compile_queryset, start_from, walk_sql

        start = start_from(self.tree_model, list(self.nodes), connection)
        if start is None:
            raise EmptyResultSet
        live = self.tree_model._default_manager.db_manager(compiler.using).all()
        sql, params = walk_sql(
            self.tree_model,
            connection,
            start=start,
            restrict=compile_queryset(live),
            include_self=True,
        )
        return f"({sql})", params

    def get_group_by_cols(self) -> list[Any]:
        return []

    def labels(self) -> list[str]:
        """The granted nodes as ``str()`` gives them, in the order given (one query)."""
        rows = {row.pk: str(row) for row in self.tree_model._base_manager.filter(pk__in=self.nodes)}
        return [rows.get(node, f"{self.tree_model.__name__} {node}") for node in self.nodes]

    def why_text(self) -> str:
        """``under 'Europe' or 'Asia'``: the filter in words, for ``karni why``."""
        return f"under {_listed([repr(label) for label in self.labels()], 'or')}"

    def __repr__(self) -> str:
        return f"SubtreeKeys({self.tree_model.__name__}, {list(self.nodes)!r})"


def _listed(items: Sequence[str], word: str = "and") -> str:
    """``'a', 'b' and 'c'``; past five items, ``and 3 more``."""
    shown = list(items[:_SHOWN])
    if len(items) > _SHOWN:
        return f"{', '.join(shown)} and {len(items) - _SHOWN} more"
    if len(shown) <= 1:
        return "".join(shown)
    return f"{', '.join(shown[:-1])} {word} {shown[-1]}"


def subtree_rows(model: type[models.Model], path: str, nodes: Iterable[Any]) -> Q | bool:
    """Experimental. The rows of ``model`` whose ``path`` is one of ``nodes`` or below one.

    ``False`` (no row) without a valid node: the tree scope never reaches
    every row. Otherwise one ``Q`` on ``path`` whose value is a
    :class:`SubtreeKeys` subquery. Raises ``E490`` for a path that does not
    end at a tree model.
    """
    resolved = resolve_path(model, path)
    keys = _node_keys(resolved.tree_model, nodes)
    if not keys:
        return False
    return Q(**{f"{path}__in": SubtreeKeys(resolved.tree_model, keys)})


# the nodes a user holds


def granted_targets(user: Any, path: str, *, permission: str | None = None) -> list[TargetGrant]:
    """Experimental. The nodes ``user`` holds under ``tree:<path>``, each with its grant.

    :func:`karni.accounts.grants.scope_targets` for the scope, read once per
    request: the answer is cached on the user per path and permission, and
    :func:`karni.accounts.grants.forget` drops it with the grants.
    """
    from karni.accounts.grants import scope_targets

    if user is None or not getattr(user, "is_authenticated", False):
        return []
    cache: dict[tuple[str, str | None], list[TargetGrant]] | None = getattr(user, CACHE_ATTR, None)
    if cache is None:
        cache = {}
        setattr(user, CACHE_ATTR, cache)
    key = (path, permission)
    if key not in cache:
        cache[key] = scope_targets(user, f"{KIND}:{path}", permission=permission)
    return list(cache[key])


def tree_rows(
    user: Any, model: type[models.Model], path: str, *, permission: str | None = None
) -> Q | bool:
    """Experimental. The rows of ``model`` under every node ``user`` holds under ``tree:<path>``.

    ``permission`` (a key or a ``KARNI_ROLES`` pattern) keeps the grants of the
    permissions it matches, ``None`` every grant of the scope. One subquery
    for all the nodes (:func:`subtree_rows`), ``False`` without one.
    """
    resolve_path(model, path)
    targets = granted_targets(user, path, permission=permission)
    return subtree_rows(model, path, [item.target for item in targets])


def source_nodes(user: Any, path: str, permission: str, source: GrantSource | Grant) -> list[str]:
    """Experimental. The nodes one grant gives: a user grant by its id, a role grant by its role.

    ``source`` is a :class:`~karni.accounts.roles.Grant` (the rows of one
    grant) or a :class:`~karni.accounts.roles.GrantSource` (``karni why``).
    A role grant gives the node ``user.<field>`` holds (the path's last step),
    the same node for every role.
    """
    from karni.accounts.grants import ORIGIN

    grant_id = getattr(source, "grant_id", "")
    role = getattr(source, "role", None)
    found: list[str] = []
    for item in granted_targets(user, path, permission=permission):
        if grant_id:
            keep = item.source.grant_id == grant_id
        else:
            keep = item.source.origin != ORIGIN and (role is None or item.source.role == role)
        if keep and item.target not in found:
            found.append(item.target)
    return found


def grant_nodes(user: Any, grant: Grant) -> list[str]:
    """Experimental. The nodes one resolved grant of ``tree:<path>`` gives ``user``."""
    return source_nodes(user, grant.scope_path, grant.permission, grant)


def tree_scope(
    model: type[models.Model], path: str, *, permission: str | None = None
) -> Callable[[Any], Q | bool]:
    """Experimental. A ``Where`` function: the rows under the nodes the requester holds.

    ``access = Access(read=Where(tree_scope(Order, "region")))`` reads the
    orders under every node the user holds under ``tree:region``, whatever
    permission the grant names, and ``permission="shop.order:view"`` keeps
    that permission's grants only. The path is checked now (``E490``), so a
    typo fails at startup. A signed-in user without a node gets an empty list,
    and an anonymous request is refused (the function answers ``False``).
    """
    resolve_path(model, path)

    def rows(request: Any) -> Q | bool:
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        found = tree_rows(user, model, path, permission=permission)
        return Q(pk__in=[]) if found is False else found

    rows.__name__ = f"tree_scope_{path}"
    rows.__qualname__ = rows.__name__
    rows.__doc__ = (
        f"The rows of {model.__name__} under the nodes the requester holds (tree:{path})."
    )
    return rows


# the access forest


@dataclass
class ForestNode:
    """Experimental. One node of an access forest.

    ``granted`` is true for a node a grant names. Its ancestors and the other
    roots are there for navigation, with ``granted`` false. ``children`` lists
    the forest's children of an ancestor, and is ``None`` for a granted node
    with children (load them from ``tree/?root=<id>``).
    """

    key: Any
    label: str
    parent: Any
    granted: bool
    has_children: bool
    children: list[ForestNode] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.key,
            "label": self.label,
            "parent": self.parent,
            "granted": self.granted,
            "has_children": self.has_children,
            "children": None
            if self.children is None
            else [child.to_dict() for child in self.children],
        }


@dataclass
class Forest:
    """Experimental. A user's access forest for one tree model (:func:`access_forest`).

    ``all`` is true when the user reaches every node (a superuser, or a grant
    of scope ``all`` of the permission asked about): every root is then
    granted. ``truncated`` is true when roots were left out to stay within
    the node limit.
    """

    results: list[ForestNode] = field(default_factory=list)
    all: bool = False
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "results": [node.to_dict() for node in self.results],
            "all": self.all,
            "truncated": self.truncated,
        }

    def granted(self) -> list[Any]:
        """The keys of the granted nodes, depth first."""
        found: list[Any] = []
        stack = list(reversed(self.results))
        while stack:
            node = stack.pop()
            if node.granted:
                found.append(node.key)
            stack.extend(reversed(node.children or []))
        return found


def _wanted(key: str, permission: str | None) -> bool:
    import fnmatch

    if permission is None:
        return True
    return fnmatch.fnmatchcase(key, "*:*" if permission == "*" else permission)


def _model_of(key: str) -> type[models.Model] | None:
    from django.apps import apps

    try:
        return apps.get_model(key.rsplit(":", 1)[0])
    except (LookupError, ValueError):
        return None


def _forest_paths(user: Any, tree_model: type[models.Model], permission: str | None) -> list[str]:
    """The tree scopes of ``user``'s grants that end at ``tree_model``, in grant order."""
    from karni.accounts.roles import grants_for

    found: list[str] = []
    for key, grants in grants_for(user).items():
        if not _wanted(key, permission):
            continue
        model = _model_of(key)
        if model is None:
            continue
        for grant in grants:
            if grant.scope != KIND or grant.scope_path in found:
                continue
            resolved = tree_path(model, grant.scope_path)
            if resolved is not None and resolved.tree_model is tree_model:
                found.append(grant.scope_path)
    return found


def _holds_all(user: Any, permission: str | None) -> bool:
    from karni.accounts.roles import grants_for

    if getattr(user, "is_superuser", False):
        return True
    if permission is None:
        return False
    return any(
        grant.scope == "all"
        for key, grants in grants_for(user).items()
        if _wanted(key, permission)
        for grant in grants
    )


def _chain(start: Any, parents: dict[Any, Any]) -> list[Any]:
    """``start`` and the nodes above it, nearest first; stops at a root or a repeat (a cycle)."""
    chain: list[Any] = []
    seen: set[Any] = set()
    current = start
    while current is not None and current in parents and current not in seen:
        seen.add(current)
        chain.append(current)
        current = parents[current]
    return chain


def access_forest(
    user: Any,
    tree_model: type[models.Model],
    *,
    permission: str | None = None,
    max_nodes: int = 1000,
) -> Forest:
    """Experimental. The nodes ``user`` holds in ``tree_model``, their ancestors and every root.

    The granted nodes come from every ``tree:<path>`` grant of the user whose
    path ends at ``tree_model`` (``permission``, a key or a pattern, keeps the
    grants of the permissions it matches). Each granted node comes with the
    path from its root, the ancestors flagged ``granted=False``, and every
    other root follows, flagged too. A granted node below another granted node
    is inside it already, so the forest shows the upper one. A cycle in the
    data never loops: the walk up is the cycle-safe one of :mod:`karni.tree`.

    Queries do not grow with the nodes: the grants (cached for the request),
    one walk up from every granted node, one read of their rows and one of
    the roots. ``max_nodes`` caps the roots that are not on a granted path
    (``truncated``).
    """
    from karni.tree import tree_order

    ordering = tuple(tree_model.tree_ordering())  # type: ignore[attr-defined]
    live = tree_model._default_manager.all()
    limit = max(1, int(max_nodes))
    roots = _with_children(live.filter(parent__isnull=True), live).order_by(*ordering)
    if _holds_all(user, permission):
        rows = list(roots[: limit + 1])
        return Forest(
            [_node(row, granted=True) for row in rows[:limit]],
            all=True,
            truncated=len(rows) > limit,
        )
    targets: list[str] = []
    for path in _forest_paths(user, tree_model, permission):
        for item in granted_targets(user, path, permission=permission):
            if item.target not in targets:
                targets.append(item.target)
    granted = _node_keys(tree_model, targets)
    parents: dict[Any, Any] = {}
    if granted:
        for key, parent, _depth in live.walk(granted, up=True, include_self=True):  # type: ignore[attr-defined]
            parents[key] = parent
    granted_set = {key for key in granted if key in parents}
    tops = [
        key
        for key in granted
        if key in granted_set and not any(up in granted_set for up in _chain(key, parents)[1:])
    ]
    needed: dict[Any, None] = {}
    for key in tops:
        for node in _chain(key, parents):
            needed[node] = None
    rows_by_key: dict[Any, Any] = {}
    if needed:
        found = _with_children(live.filter(pk__in=list(needed)), live).order_by(*ordering)
        rows_by_key = {row.pk: row for row in found}
    built = {
        key: _node(row, granted=key in tops, children=None if key in tops else [])
        for key, row in rows_by_key.items()
    }
    # Depth first from the roots of the paths: a node is placed once, under the node the
    # walk reached it from, so a cycle in the data never makes the forest loop.
    tops_level: list[ForestNode] = []
    for key, depth in tree_order([(key, parents.get(key)) for key in rows_by_key]):
        node = built[key]
        holder = built.get(parents.get(key)) if depth > 0 else None
        if holder is None or holder.children is None:
            tops_level.append(node)
        else:
            holder.children.append(node)
            holder.has_children = True
    room = max(0, limit - len(built))
    placed = {node.key for node in tops_level}
    results: list[ForestNode] = []
    added = 0
    truncated = False
    for row in roots[: room + len(placed) + 1]:
        if row.pk in placed:
            results.append(built[row.pk])
            placed.discard(row.pk)
        elif row.pk in built:
            continue
        elif added < room:
            results.append(_node(row, granted=False, children=[], has_children=False))
            added += 1
        else:
            truncated = True
    # A granted path whose top is not a root (its parent is soft-deleted, or a cycle) last.
    results.extend(node for node in tops_level if node.key in placed)
    return Forest(results, all=False, truncated=truncated)


def _with_children(queryset: Any, live: Any) -> Any:
    return queryset.annotate(tree_has_children=Exists(live.filter(parent=OuterRef("pk"))))


def _node(
    row: Any,
    *,
    granted: bool,
    children: list[ForestNode] | None = None,
    has_children: bool | None = None,
) -> ForestNode:
    """A forest node; ``children=None`` on a node with children means "not loaded"."""
    kids = bool(row.tree_has_children) if has_children is None else has_children
    if children is None and not kids:
        children = []
    return ForestNode(
        key=row.pk,
        label=str(row),
        parent=getattr(row, "parent_id", None),
        granted=granted,
        has_children=kids,
        children=children,
    )


# why a row is in or out


@dataclass(frozen=True)
class RowVerdict:
    """Experimental. Which granted node a row is under, for one grant (:func:`explain_row`).

    ``nodes`` are the grant's nodes and ``values`` the row's own nodes on the
    path, each as ``(key, label)``. ``under`` is ``(row node, granted node)``
    for the first row node inside a granted subtree, else ``None``.
    ``row`` is false when no row was asked about (``karni why-empty``).
    """

    path: str
    nodes: tuple[tuple[Any, str], ...]
    values: tuple[tuple[Any, str], ...]
    under: tuple[tuple[Any, str], tuple[Any, str]] | None
    row: bool = True

    def text(self, given: str) -> str:
        """``<given> targets Europe, and this row's region Lyon is under it``."""
        names = _listed([label for _key, label in self.nodes])
        holds = f"{given} targets {names}" if self.nodes else f"{given} gives no node"
        if not self.row:
            return holds if self.nodes else f"{holds}, so it reaches no row"
        if not self.values:
            return f"{holds}, and this row has no {self.path}"
        if self.under is not None:
            (_vk, value), (_nk, node) = self.under
            it = "it" if len(self.nodes) == 1 and value != node else node
            if value == node:
                return f"{holds}, and this row's {self.path} is {node}"
            return f"{holds}, and this row's {self.path} {value} is under {it}"
        values = _listed([label for _key, label in self.values])
        if not self.nodes:
            return f"{holds}, so this row's {self.path} {values} is outside it"
        return f"{holds}, and this row's {self.path} {values} is under none of them"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "nodes": [{"id": str(key), "label": label} for key, label in self.nodes],
            "values": [{"id": str(key), "label": label} for key, label in self.values],
            "under": None
            if self.under is None
            else {"value": str(self.under[0][0]), "node": str(self.under[1][0])},
        }


def explain_row(
    model: type[models.Model], path: str, row: models.Model | None, nodes: Iterable[Any]
) -> RowVerdict:
    """Experimental. Whether ``row``'s nodes on ``path`` are under one of ``nodes``, and which.

    Three queries: the row's nodes, one walk up from them, and the labels.
    Without a row, the verdict only names the nodes (one query).
    """
    resolved = resolve_path(model, path)
    tree_model = resolved.tree_model
    keys = _node_keys(tree_model, nodes)
    values: list[Any] = []
    if row is not None:
        raw = model._base_manager.filter(pk=row.pk).values_list(path, flat=True)
        values = _node_keys(tree_model, [value for value in raw if value is not None])
    parents: dict[Any, Any] = {}
    if values:
        walked = tree_model._default_manager.walk(values, up=True, include_self=True)  # type: ignore[attr-defined]
        for key, parent, _depth in walked:
            parents[key] = parent
    wanted = set(keys)
    under: tuple[Any, Any] | None = None
    for value in values:
        for above in _chain(value, parents):
            if above in wanted:
                under = (value, above)
                break
        if under is not None:
            break
    labels = {
        node.pk: str(node) for node in tree_model._base_manager.filter(pk__in=[*keys, *values])
    }

    def pair(key: Any) -> tuple[Any, str]:
        return key, labels.get(key, f"{tree_model.__name__} {key}")

    return RowVerdict(
        path=path,
        nodes=tuple(pair(key) for key in keys),
        values=tuple(pair(key) for key in values),
        under=None if under is None else (pair(under[0]), pair(under[1])),
        row=row is not None,
    )
