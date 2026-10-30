"""Experimental. The walks behind tree models: recursive SQL that never loops.

:class:`karni.models.TreeModel` stores a hierarchy as a ``parent`` foreign key
to the same table. Reading a branch, the path to a node or the order of a
whole tree then needs a recursive query, and real data contains cycles (a row
edited by hand, an import, a bug elsewhere), so every walk here is cycle safe:

* PostgreSQL: a ``WITH RECURSIVE`` query with the ``CYCLE`` clause (PostgreSQL
  14 and later). A row that closes a cycle is marked and never walked again.
* SQLite (and any other database): the same query carrying the path of keys
  walked so far, and a step never enters a key already on its path.

Each walk is one statement. The querysets of :class:`karni.managers.TreeQuerySet`
put it inside ``pk IN (...)``, so a branch stays a lazy, chainable queryset.
A walk follows only the rows of the queryset it starts from: on the default
manager that is the live rows, so a soft-deleted node hides its branch, and
on an access-scoped queryset a row the requester cannot read hides its
branch too.

This module also holds the tree errors and :func:`tree_order`, the depth-first
order the admin changelist shows.

Override / escape hatch: :func:`walk_sql` is the one place the SQL is built.
Call it for a walk the querysets do not offer, or override the queryset
methods on a :class:`karni.managers.TreeQuerySet` subclass.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.db import models

from karni.conflicts import KarniConflict
from karni.exceptions import KarniValueError

if TYPE_CHECKING:
    from django.db.backends.base.base import BaseDatabaseWrapper

__all__ = [
    "TreeCycleError",
    "TreeHasChildren",
    "TreeSpec",
    "is_tree_model",
    "tree_order",
    "tree_spec",
    "walk_sql",
]

#: The name of the recursive query and its columns inside a walk.
_CTE = "karni_tree"


class TreeCycleError(KarniValueError):
    """Experimental. The new parent is the node itself or one of its descendants (``E340``)."""

    code = "E340"

    def __init__(self, message: str, *, code: str | None = None, field: str = "parent") -> None:
        super().__init__(message, code=code)
        self.field = field


class TreeHasChildren(KarniConflict):
    """Experimental. A node with live children cannot be deleted alone (``E341``, HTTP 409)."""

    code = "E341"


@dataclass(frozen=True)
class TreeSpec:
    """Experimental. What makes a model a tree: its parent field and whether siblings are ordered.

    ``parent`` is the self-referencing foreign key and ``position`` the sibling
    order field (``None`` for an unordered tree). The OpenAPI document
    publishes it as ``x-karni-tree``.
    """

    parent: str
    position: str | None

    @property
    def ordered(self) -> bool:
        return self.position is not None

    def as_extension(self) -> dict[str, Any]:
        """The ``x-karni-tree`` value: ``{"parent": "parent", "ordered": bool}``."""
        return {"parent": self.parent, "ordered": self.ordered}


def is_tree_model(model: Any) -> bool:
    """Experimental. Whether ``model`` is a :class:`karni.models.TreeModel` (a class or a row)."""
    from karni.models import TreeModel

    cls = model if isinstance(model, type) else type(model)
    return issubclass(cls, TreeModel)


def tree_spec(model: Any) -> TreeSpec | None:
    """Experimental. The :class:`TreeSpec` of a tree model, else ``None``."""
    if not is_tree_model(model):
        return None
    from karni.models import OrderedTreeModel

    cls = model if isinstance(model, type) else type(model)
    ordered = issubclass(cls, OrderedTreeModel)
    return TreeSpec(parent="parent", position="position" if ordered else None)


# the walk


def _pk_params(model: type[models.Model], values: Iterable[Any], connection: Any) -> list[Any]:
    """Database values for primary keys given as rows, keys or strings (``E343`` on a bad one)."""
    field = model._meta.pk
    assert field is not None
    params: list[Any] = []
    for value in values:
        if isinstance(value, models.Model):
            if value._meta.concrete_model is not model._meta.concrete_model:
                raise KarniValueError(
                    f"A {type(value).__name__} row was passed to a walk of {model.__name__}. "
                    f"Pass {model.__name__} rows or their keys.",
                    code="E343",
                )
            value = value.pk
        if value is None:
            raise KarniValueError(
                f"A walk of {model.__name__} got None (or an unsaved row) as a node. Pass "
                "saved rows or their keys.",
                code="E343",
            )
        try:
            value = field.to_python(value)
        except ValidationError as exc:
            raise KarniValueError(
                f"{value!r} is not a key of {model.__name__} ({type(field).__name__}).",
                code="E343",
            ) from exc
        params.append(field.get_db_prep_value(value, connection, prepared=False))
    return params


def compile_queryset(queryset: models.QuerySet[Any]) -> tuple[str, tuple[Any, ...]] | None:
    """``SELECT pk`` of ``queryset`` as SQL and params, or ``None`` when it filters nothing.

    A queryset with no ``WHERE`` (``Model._base_manager.all()``) needs no
    restriction, so the walk skips the subquery. Raises
    :class:`django.core.exceptions.EmptyResultSet` for ``.none()``.
    """
    if not queryset.query.where:
        return None
    inner = queryset.order_by().values("pk")
    sql, params = inner.query.get_compiler(using=queryset.db).as_sql()
    return sql, tuple(params)


def walk_sql(
    model: type[models.Model],
    connection: BaseDatabaseWrapper,
    *,
    start: tuple[str, Sequence[Any]],
    up: bool = False,
    restrict: tuple[str, Sequence[Any]] | None = None,
    max_depth: int | None = None,
    include_self: bool = False,
    select: str = "node_id",
    where: str = "",
    where_params: Sequence[Any] = (),
    order_limit: str = "",
) -> tuple[str, list[Any]]:
    """Experimental. One cycle-safe recursive walk over ``model``'s table, as SQL and params.

    ``start`` is the SQL of the starting keys (``"%s, %s"`` with its params, or
    a subquery selecting keys). The walk goes to the children (``up=False``)
    or the parents (``up=True``), at most ``max_depth`` steps, through rows
    whose key is in ``restrict`` (a subquery, or ``None`` for every row).
    Each row of the walk has ``node_id``, ``parent_id`` and ``depth`` (0 for
    the start rows, which ``include_self=False`` leaves out); ``select``,
    ``where`` and ``order_limit`` shape the final ``SELECT``.
    """
    quote = connection.ops.quote_name
    table = quote(model._meta.db_table)
    pk_field = model._meta.pk
    assert pk_field is not None
    pk = f"t.{quote(pk_field.column)}"
    parent = f"t.{quote(model._meta.get_field('parent').column)}"  # type: ignore[union-attr]
    cte = quote(_CTE)
    join = f"{pk} = w.parent_id" if up else f"{parent} = w.node_id"
    start_sql, start_params = start
    params: list[Any] = [*start_params]
    restrict_sql = ""
    restrict_params: list[Any] = []
    if restrict is not None:
        restrict_sql = f" AND {pk} IN ({restrict[0]})"
        restrict_params = [*restrict[1]]
    params += restrict_params
    depth_sql = ""
    depth_params: list[Any] = []
    if max_depth is not None:
        depth_sql = " AND w.depth < %s"
        depth_params = [int(max_depth)]
    postgres = connection.vendor == "postgresql"
    if postgres:
        columns = "node_id, parent_id, depth"
        base_extra = ""
        step_extra = ""
        guard = "TRUE"
        tail = " CYCLE node_id SET is_cycle USING cycle_path"
        final = "NOT is_cycle"
    else:
        # The path of keys walked so far ('/3/7/'): a step never enters a key on it.
        columns = "node_id, parent_id, depth, path"
        base_extra = f", '/' || {pk} || '/'"
        step_extra = f", w.path || {pk} || '/'"
        guard = f"instr(w.path, '/' || {pk} || '/') = 0"
        tail = ""
        final = "1 = 1"
    params += [*depth_params, *restrict_params]
    final += " AND depth >= 0" if include_self else " AND depth > 0"
    if where:
        final += f" AND ({where})"
    params += [*where_params]
    sql = (
        f"WITH RECURSIVE {cte}({columns}) AS ("
        f"SELECT {pk}, {parent}, 0{base_extra} FROM {table} t "
        f"WHERE {pk} IN ({start_sql}){restrict_sql} "
        "UNION ALL "
        f"SELECT {pk}, {parent}, w.depth + 1{step_extra} FROM {table} t "
        f"INNER JOIN {cte} w ON {join} "
        f"WHERE {guard}{depth_sql}{restrict_sql}"
        f"){tail} "
        f"SELECT {select} FROM {cte} WHERE {final}"
    )
    if order_limit:
        sql += f" {order_limit}"
    return sql, params


def start_from(
    model: type[models.Model], nodes: Any, connection: Any
) -> tuple[str, tuple[Any, ...]] | None:
    """The ``start`` of :func:`walk_sql` for a row, a key, an iterable of them or a queryset.

    ``None`` when there is nothing to start from (an empty list, ``.none()``).
    """
    from django.core.exceptions import EmptyResultSet

    if isinstance(nodes, models.QuerySet):
        if nodes.model._meta.concrete_model is not model._meta.concrete_model:
            raise KarniValueError(
                f"A queryset of {nodes.model.__name__} was passed to a walk of {model.__name__}.",
                code="E343",
            )
        try:
            sql, params = nodes.order_by().values("pk").query.get_compiler(using=nodes.db).as_sql()
        except EmptyResultSet:
            return None
        return sql, tuple(params)
    if (
        isinstance(nodes, models.Model)
        or isinstance(nodes, str | bytes)
        or not isinstance(nodes, Iterable)
    ):
        nodes = [nodes]
    params = _pk_params(model, nodes, connection)
    if not params:
        return None
    return ", ".join(["%s"] * len(params)), tuple(params)


# depth-first order (the admin changelist)


def tree_order(rows: Sequence[tuple[Any, Any]]) -> list[tuple[Any, int]]:
    """Experimental. ``(key, parent key)`` pairs in depth-first order, each with its depth.

    ``rows`` come in sibling order (the order a node's children are shown).
    A row whose parent is not among them starts a branch at depth 0, so a
    filtered list still nests what it can. Rows on a cycle that no branch
    reaches are appended at depth 0, each once: the order never loops.
    """
    keys = {key for key, _parent in rows}
    children: dict[Any, list[Any]] = {}
    tops: list[Any] = []
    for key, parent in rows:
        if parent is None or parent not in keys or parent == key:
            tops.append(key)
        else:
            children.setdefault(parent, []).append(key)
    ordered: list[tuple[Any, int]] = []
    seen: set[Any] = set()

    def visit(top: Any) -> None:
        stack: list[tuple[Any, int]] = [(top, 0)]
        while stack:
            key, depth = stack.pop()
            if key in seen:
                continue
            seen.add(key)
            ordered.append((key, depth))
            stack.extend((child, depth + 1) for child in reversed(children.get(key, ())))

    for top in tops:
        visit(top)
    for key, _parent in rows:
        if key not in seen:
            visit(key)  # on a cycle no top reaches
    return ordered
