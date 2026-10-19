"""Row filters: ``True`` (every row), ``False`` (no row) or a ``Q``, and how they combine.

Shared by the access predicates (:mod:`karni.api.access`), the roles tier
(:mod:`karni.accounts.roles`) and the admin (:mod:`karni.admin.scope`), so a
row policy compiled once applies the same way on every surface. Nothing here
imports DRF.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import FieldDoesNotExist
from django.db.models import Model, Q, QuerySet
from django.db.models.constants import LOOKUP_SEP

__all__ = ["RowFilter", "apply_rows", "combine_and", "combine_or", "spawns_duplicates"]

type RowFilter = bool | Q
"""Row-level answer: ``True`` (every row), ``False`` (no row) or a ``Q``."""


def combine_or(left: RowFilter, right: RowFilter) -> RowFilter:
    if left is True or right is True:
        return True
    if left is False:
        return right
    if right is False:
        return left
    return left | right


def combine_and(left: RowFilter, right: RowFilter) -> RowFilter:
    if left is False or right is False:
        return False
    if left is True:
        return right
    if right is True:
        return left
    return left & right


def spawns_duplicates(model: type[Model], node: Q) -> bool:
    """True when any lookup in ``node`` crosses a to-many relation."""
    for child in node.children:
        if isinstance(child, Q):
            if spawns_duplicates(model, child):
                return True
            continue
        if not isinstance(child, tuple):
            continue  # expressions (Exists, …) add no join
        opts = model._meta
        for name in str(child[0]).split(LOOKUP_SEP):
            if name == "pk":
                name = opts.pk.name
            try:
                relation = opts.get_field(name)
            except FieldDoesNotExist:
                break  # a lookup/transform: the path ended
            path_infos = getattr(relation, "path_infos", None)
            if not path_infos:
                break
            if any(info.m2m for info in path_infos):
                return True
            opts = path_infos[-1].to_opts
    return False


def apply_rows(queryset: QuerySet[Any], rows: RowFilter) -> QuerySet[Any]:
    """Narrow ``queryset`` by a row filter (``distinct()`` for to-many paths)."""
    if rows is True:
        return queryset
    if rows is False:
        return queryset.none()
    narrowed = queryset.filter(rows)
    if spawns_duplicates(queryset.model, rows):
        narrowed = narrowed.distinct()
    return narrowed
