"""Related rows in a response are only the ones the requester may read (ADR 0001 Q2.5).

``?expand=`` embeds related rows, to-many relations render as lists of
primary keys, and an export names related rows by their natural key. On a
``list`` or ``retrieve`` the optimiser already fetches every one of them
through the target's read scope (:mod:`karni.api.optimizer`). Other
responses render rows it never shaped: a write's response (``create`` and
``update`` render the saved instance), a viewset with ``optimize = False``,
a ``select_related`` / ``prefetch_related`` hint that wins over the scoped
lookup, or a custom action. This module is the check the generated
serializers and the exporter run at render time, so the read scope holds
on every path:

* rows fetched through a read scope carry a marker
  (:func:`mark_read_scoped`, applied by ``BaseViewSet.target_scope``) and
  render as they are, so the optimised path costs no extra query;
* every other related row is checked against its model's read scope for
  this request, in one query per model and batch, remembered in the
  serializer context. An unreadable to-one renders as ``null`` and an
  unreadable to-many member is left out, which is what the optimised path
  renders.

The scope is the one relation validation uses
(:func:`karni.api.access.target_read_scope`: the ``access.read`` of the
viewset routed for the related model). Without a request in the serializer
context nothing is narrowed (server-side rendering).

Override / escape hatch: put another scope in the serializer context under
:data:`SCOPE_KEY`, a ``(queryset) -> (narrowed queryset, filtered)``
callable (the admin's export passes the admin's row scope), or ``None`` to
narrow nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, MutableMapping
from dataclasses import dataclass, field
from typing import Any, Final

from django.db.models import BooleanField, Model, QuerySet, Value

__all__ = [
    "READ_SCOPED",
    "SCOPE_KEY",
    "RelatedScope",
    "mark_read_scoped",
    "readable_related",
    "related_scope",
]

READ_SCOPED: Final = "_karni_read_scoped"
"""Annotation (and so instance attribute) on rows fetched through a read scope."""

SCOPE_KEY: Final = "karni_related_scope"
"""Serializer-context key naming the scope for related rows (see the module docstring)."""

_CACHE_KEY: Final = "_karni_related_rows"

type RelatedScope = Callable[[QuerySet[Any]], tuple[QuerySet[Any], bool]]
"""``(queryset) -> (the rows of it the requester may read, whether that narrowed anything)``."""

_UNSET: Final = object()


def mark_read_scoped(queryset: QuerySet[Any]) -> QuerySet[Any]:
    """``queryset`` whose rows say they came through the requester's read scope."""
    if READ_SCOPED in queryset.query.annotations:
        return queryset
    return queryset.annotate(**{READ_SCOPED: Value(True, output_field=BooleanField())})


def related_scope(context: Any) -> RelatedScope | None:
    """The scope for related rows rendered with ``context``, or ``None`` (nothing narrowed).

    ``context[SCOPE_KEY]`` when the context names one; otherwise the read
    scope of the routed viewsets for ``context["request"]``.
    """
    if not isinstance(context, Mapping):
        return None
    explicit = context.get(SCOPE_KEY, _UNSET)
    if explicit is not _UNSET:
        return explicit  # type: ignore[no-any-return]
    request = context.get("request")
    if request is None:
        return None

    def scope(queryset: QuerySet[Any]) -> tuple[QuerySet[Any], bool]:
        from karni.api.access import target_read_scope

        return target_read_scope(queryset, request)

    return scope


@dataclass
class _Known:
    """What one render learned about one related model's rows."""

    filtered: bool | None = None
    readable: set[Any] = field(default_factory=set)
    checked: set[Any] = field(default_factory=set)


def _cache(context: Any) -> dict[type[Model], _Known]:
    if isinstance(context, MutableMapping):
        found: dict[type[Model], _Known] = context.setdefault(_CACHE_KEY, {})
        return found
    return {}


def _unproven(row: Any) -> bool:
    """A saved model row that did not come through a read scope."""
    return isinstance(row, Model) and row.pk is not None and not getattr(row, READ_SCOPED, False)


def readable_related(context: Any, rows: Iterable[Any]) -> list[Any]:
    """``rows`` (related rows about to be rendered with ``context``) minus the unreadable ones.

    Rows carrying the :func:`mark_read_scoped` marker are kept without a
    query; the others are checked against their model's scope in one query
    per model, and the answer is remembered in ``context`` for the rest of
    the render.
    """
    items = list(rows)
    scope = related_scope(context)
    if scope is None or not any(_unproven(row) for row in items):
        return items
    pending: dict[type[Model], set[Any]] = {}
    for row in items:
        if _unproven(row):
            pending.setdefault(type(row), set()).add(row.pk)
    known = _cache(context)
    for model, pks in pending.items():
        entry = known.setdefault(model, _Known())
        unknown = pks - entry.checked
        if entry.filtered is False or not unknown:
            continue
        scoped, filtered = scope(model._default_manager.filter(pk__in=unknown))
        entry.filtered = bool(filtered)
        if filtered:
            entry.readable.update(scoped.values_list("pk", flat=True))
        entry.checked.update(unknown)
    return [
        row
        for row in items
        if not _unproven(row)
        or known[type(row)].filtered is False
        or row.pk in known[type(row)].readable
    ]
