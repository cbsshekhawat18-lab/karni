"""Indexes that declared API usage needs, and whether the model has them.

A viewset that declares ``search_fields``, ``filterset_fields``,
``ordering_fields`` or an ``ordering`` asks the database to find or sort rows
by those columns on every list request. Each such column needs an index, or
every request reads the whole table. :func:`usage_requirements` derives
them from the routed viewsets; :func:`covering_index` says which existing
index or constraint serves each one (a primary key, a unique constraint, a
``db_index``, an FK's index, or any ``Meta.indexes`` entry that starts with
the column); system check ``karni.W967`` and ``karni schema`` report the
rest with the exact line to add.

Search is different: a B-tree cannot serve ``?search=``. A column a
``SearchField`` covers is served by its GIN index; any other searched text
column needs a ``SearchField`` (or a trigram GIN index for the trigram leg).

Indexes are recommended, not added behind your back: migrations come from
the models, and a model must not change shape depending on which API
modules happen to be imported.

Override / escape hatch: add the index (or a ``SearchField``) the message
names, or silence ``karni.W967`` for a table small enough to scan.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from django.db import models

__all__ = ["Requirement", "covering_index", "suggestion", "usage_requirements"]


@dataclass(frozen=True)
class Requirement:
    """One column a viewset's declaration needs indexed."""

    model: type[models.Model]
    field: str
    #: ``search``, ``filter`` or ``order``.
    kind: str
    #: ``EventViewSet.search_fields``.
    declared_by: str


def _names(value: Any) -> list[str]:
    if not value or value == "__all__":
        return []
    if isinstance(value, dict):
        return [str(key) for key in value]
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value if isinstance(item, str)]


def _local_field(model: type[models.Model], path: str) -> Any | None:
    name = path.lstrip("-^=@$").split("__", 1)[0]
    try:
        field = model._meta.get_field(name)
    except Exception:  # noqa: BLE001 - a bad name is the viewset's own error
        return None
    if not getattr(field, "concrete", False) or field.many_to_many:
        return None
    return field


def usage_requirements(viewsets: Iterable[type[Any]]) -> list[Requirement]:
    """Every (model, column, kind) the given viewsets' declarations need indexed."""
    found: dict[tuple[Any, str, str], Requirement] = {}
    for viewset in viewsets:
        model = getattr(viewset, "model", None) or getattr(
            getattr(viewset, "queryset", None), "model", None
        )
        if model is None:
            continue
        declared: list[tuple[str, str, list[str]]] = [
            ("search", "search_fields", _names(getattr(viewset, "search_fields", None))),
            ("filter", "filterset_fields", _names(getattr(viewset, "filterset_fields", None))),
            ("order", "ordering_fields", _names(getattr(viewset, "ordering_fields", None))),
        ]
        ordering = viewset.__dict__.get("ordering")
        if isinstance(ordering, list | tuple):
            declared.append(("order", "ordering", _names(ordering)))
        for kind, attribute, paths in declared:
            for path in paths:
                field = _local_field(model, path)
                if field is None:
                    continue
                key = (model, field.name, kind)
                found.setdefault(
                    key, Requirement(model, field.name, kind, f"{viewset.__name__}.{attribute}")
                )
    return list(found.values())


def _leading(model: type[models.Model], entry: Any) -> str | None:
    fields = list(getattr(entry, "fields", None) or ())
    if fields:
        return str(fields[0]).lstrip("-")
    return None


def covering_index(model: type[models.Model], name: str, kind: str) -> str | None:
    """What serves ``kind`` (``search``/``filter``/``order``) on ``name``, or ``None``."""
    from karni.fields.indexes import GinIndex
    from karni.fields.search import SearchField

    field: Any = model._meta.get_field(name)
    if kind == "search":
        for other in model._meta.concrete_fields:
            if isinstance(other, SearchField) and (other.name == name or name in other.sources):
                return f"SearchField {other.name} (GIN)"
        for index in model._meta.indexes:
            opclasses = list(getattr(index, "opclasses", ()) or ())
            if _leading(model, index) == name and "gin_trgm_ops" in opclasses:
                return f"index {index.name} (trigram GIN)"
            if isinstance(index, GinIndex) and _leading(model, index) == name:
                return f"index {index.name} (GIN)"
        return None
    if field.primary_key:
        return "primary key"
    if field.unique:
        return "unique column"
    if field.db_index:
        return "ForeignKey index" if field.is_relation else "db_index"
    for index in model._meta.indexes:
        if _leading(model, index) == name and not isinstance(index, GinIndex):
            return f"index {index.name}"
    for constraint in model._meta.constraints:
        if isinstance(constraint, models.UniqueConstraint) and _leading(model, constraint) == name:
            partial = " (live rows)" if constraint.condition is not None else ""
            return f"unique constraint {constraint.name}{partial}"
    for together in model._meta.unique_together:
        if together and together[0] == name:
            return "unique_together"
    return None


def suggestion(requirement: Requirement, searched: list[str] | None = None) -> str:
    """The exact declaration that covers ``requirement``.

    For search, ``searched`` is every uncovered column the same declaration
    searches: one ``SearchField`` covers them all.
    """
    from karni.fields.base import object_name

    model = requirement.model
    if requirement.kind == "search":
        sources = ", ".join(f'"{name}"' for name in (searched or [requirement.field]))
        return (
            f"add `search = SearchField(sources=[{sources}])` (from karni.fields) to "
            f'{model.__name__} and list "search" in search_fields'
        )
    column = model._meta.get_field(requirement.field).column
    index_name = object_name(model, [column], "idx", limit=30)
    return (
        f'add `models.Index(fields=["{requirement.field}"], name="{index_name}")` to '
        f"{model.__name__}.Meta.indexes"
    )
