"""Composable querysets, and the scoped managers behind Karni's model mixins.

Each model mixin in :mod:`karni.models` has a matching queryset here. They
all extend :class:`KarniQuerySet`, so any combination composes by plain
multiple inheritance; ``BaseQuerySet`` is the four stacked. Chaining works
across them: ``Event.objects.created_since(t).created_by(u)``.

Default managers run the named-scope pipeline (:mod:`karni.scopes`) through
:class:`ScopedManagerMixin`. Every queryset they build is filtered by each
active scope covering the model, ``soft_delete`` first.
``objects.without("soft_delete", reason="...")`` lifts exactly that scope.

Override / escape hatch: subclass any queryset, then build a manager the way
:class:`BaseManager` is built,
``class EventManager(ScopedManagerMixin, Manager.from_queryset(EventQuerySet))``,
and redeclare ``objects`` on your model.
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import TYPE_CHECKING, Any, NoReturn, Self

from django.db import models
from django.db.models.manager import ManagerDescriptor
from django.utils import timezone

from karni.deprecation import warn_deprecated
from karni.scopes import SOFT_DELETE, ScopeError, apply_scopes, registry

if TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser

__all__ = [
    "AuditedQuerySet",
    "BaseManager",
    "BaseQuerySet",
    "KarniQuerySet",
    "ScopedManagerMixin",
    "SoftDeleteManager",
    "SoftDeleteQuerySet",
    "TimestampedQuerySet",
    "TreeManager",
    "TreeQuerySet",
]

#: Every soft-delete alias deprecated in 0.2 is removed in 1.0; each warning
#: links its own migration note in ``docs/migrations/0.2.md``.
_REMOVED_IN = "1.0"
_LIFT_SOFT_DELETE = 'objects.without("soft_delete", reason=...)'


class KarniQuerySet(models.QuerySet):
    """Root of every Karni queryset: filters valid on any model.

    Its bulk writes (``update()``, ``delete()``, ``bulk_create()``,
    ``bulk_update()``) send no per-row signal, so each one invalidates the
    API response cache of the models it wrote, once per call
    (:mod:`karni.api.caching`, a no-op while ``KARNI_API_CACHE`` is off).
    """

    def by_ids(self, ids: Any) -> Self:
        """Rows whose primary key is in ``ids`` (any iterable)."""
        return self.filter(pk__in=list(ids))

    def update(self, **kwargs: Any) -> int:
        """Django's ``update()``, then the response cache of the model is invalidated."""
        from karni.api.caching import invalidate

        count = super().update(**kwargs)
        if count:
            invalidate(self.model)
        return int(count)

    update.alters_data = True  # type: ignore[attr-defined]

    def delete(self) -> tuple[int, dict[str, int]]:
        """Django's ``delete()``, then the response cache of every model it deleted from."""
        from karni.api.caching import invalidation_batch

        with invalidation_batch():
            deleted, per_model = super().delete()
            _invalidate_deleted(self.model, per_model)
        return deleted, per_model

    delete.queryset_only = True  # type: ignore[attr-defined]
    delete.alters_data = True  # type: ignore[attr-defined]

    def bulk_create(self, objs: Any, *args: Any, **kwargs: Any) -> list[Any]:
        """Django's ``bulk_create()``, then the response cache of the model is invalidated."""
        from karni.api.caching import invalidate, invalidation_batch

        with invalidation_batch():
            created = super().bulk_create(objs, *args, **kwargs)
            if created:
                invalidate(self.model)
        return list(created)

    bulk_create.alters_data = True  # type: ignore[attr-defined]

    def bulk_update(self, objs: Any, fields: Any, batch_size: int | None = None) -> int:
        """Django's ``bulk_update()``, then the response cache of the model is invalidated."""
        from karni.api.caching import invalidate, invalidation_batch

        with invalidation_batch():
            count = super().bulk_update(objs, fields, batch_size=batch_size)
            if count:
                invalidate(self.model)
        return int(count)

    bulk_update.alters_data = True  # type: ignore[attr-defined]

    def without(self, *names: str, reason: str = "") -> NoReturn:
        """Not on querysets: a scope is lifted on the manager, before it applies."""
        quoted = ", ".join(f'"{name}"' for name in names) or '"<scope>"'
        raise ScopeError(
            "without() is a manager method: a queryset has already applied every scope. "
            f"Start from the manager: {self.model.__name__}.objects.without({quoted}, "
            'reason="...").filter(...)',
            code="E005",
        )

    without.queryset_only = True  # type: ignore[attr-defined]


def _invalidate_deleted(model: type[models.Model], per_model: dict[str, int]) -> None:
    """Invalidate the response cache of each model a ``delete()`` removed rows from."""
    from karni.api.caching import cache_enabled, invalidate

    if not cache_enabled():
        return
    registry = model._meta.apps
    for label, count in per_model.items():
        if not count:
            continue
        try:
            invalidate(registry.get_model(label))
        except LookupError:
            invalidate(model)


class TimestampedQuerySet(KarniQuerySet):
    """Filters over ``created_at`` / ``updated_at`` (see ``TimestampedModel``)."""

    def created_since(self, when: datetime) -> Self:
        return self.filter(created_at__gte=when)

    def created_between(self, start: datetime, end: datetime) -> Self:
        """Rows created in the half-open interval ``[start, end)``."""
        return self.filter(created_at__gte=start, created_at__lt=end)

    def updated_since(self, when: datetime) -> Self:
        return self.filter(updated_at__gte=when)

    def newest_first(self) -> Self:
        return self.order_by("-created_at")


class SoftDeleteQuerySet(KarniQuerySet):
    """QuerySet whose ``delete()`` soft-deletes by stamping ``deleted_at``.

    Hard deletion never happens implicitly: it is only ever the explicit
    :meth:`hard_delete`. ``delete``, ``hard_delete`` and ``restore`` are
    ``queryset_only``, so none is copied onto managers — ``Model.objects.delete()``
    does not exist; bulk changes start from a queryset, keeping them deliberate.
    """

    def delete(self) -> tuple[int, dict[str, int]]:
        """Soft-delete every row: one ``UPDATE`` of ``deleted_at``.

        Returns Django's ``(count, {model_label: count})`` shape. Sends no
        ``pre_delete``/``post_delete`` signals and does not cascade; being a
        bulk ``update()`` it also leaves ``updated_at`` untouched.
        """
        count = self.update(deleted_at=timezone.now())
        return count, {self.model._meta.label: count}

    delete.queryset_only = True  # type: ignore[attr-defined]
    delete.alters_data = True  # type: ignore[attr-defined]

    def hard_delete(self) -> tuple[int, dict[str, int]]:
        """Really delete the rows (Django's ``QuerySet.delete``), cascading as usual."""
        return KarniQuerySet.delete(self)

    hard_delete.queryset_only = True  # type: ignore[attr-defined]
    hard_delete.alters_data = True  # type: ignore[attr-defined]

    def restore(self) -> int:
        """Un-delete every row in the queryset; returns the number restored."""
        return self.filter(deleted_at__isnull=False).update(deleted_at=None)

    restore.queryset_only = True  # type: ignore[attr-defined]
    restore.alters_data = True  # type: ignore[attr-defined]

    def alive(self) -> Self:
        """Only rows that are not soft-deleted."""
        return self.filter(deleted_at__isnull=True)

    def dead(self) -> Self:
        """Only rows that are soft-deleted."""
        return self.filter(deleted_at__isnull=False)


class AuditedQuerySet(KarniQuerySet):
    """Filters over ``created_by`` / ``updated_by`` (see ``AuditedModel``)."""

    def created_by(self, user: AbstractBaseUser | None) -> Self:
        return self.filter(created_by=user)

    def updated_by(self, user: AbstractBaseUser | None) -> Self:
        return self.filter(updated_by=user)

    def touched_by(self, user: AbstractBaseUser) -> Self:
        """Rows the user created or last updated."""
        return self.filter(models.Q(created_by=user) | models.Q(updated_by=user))


class BaseQuerySet(TimestampedQuerySet, SoftDeleteQuerySet, AuditedQuerySet):
    """Everything above, for :class:`karni.models.BaseModel`."""


class TreeQuerySet(BaseQuerySet):
    """Experimental. :class:`BaseQuerySet` plus the walks of a :class:`karni.models.TreeModel`.

    ``roots()`` and ``children(node)`` are plain filters. ``descendants()``,
    ``ancestors()`` and ``subtree_ids()`` each run one cycle-safe recursive
    query (:mod:`karni.tree`): data that contains a cycle never makes them
    loop. Siblings come in the model's :meth:`~karni.models.TreeModel.tree_ordering`.

    A walk follows only the rows of the queryset it starts from. On
    ``Region.objects`` those are the live rows, so a soft-deleted node hides
    its branch; on a filtered queryset a row the filter removes hides its
    branch too. To filter the result instead, filter after the walk:
    ``Region.objects.descendants(europe).filter(kind="city")``.

    Override / escape hatch: subclass it and build the manager the way
    :class:`TreeManager` is built.
    """

    def _ordering(self) -> tuple[Any, ...]:
        ordering: tuple[Any, ...] = tuple(self.model.tree_ordering())  # type: ignore[attr-defined]
        return ordering

    def roots(self) -> Self:
        """The nodes without a parent, in sibling order."""
        return self.filter(parent__isnull=True).order_by(*self._ordering())

    def children(self, node: Any) -> Self:
        """The direct children of ``node`` (a row or its key), in sibling order."""
        return self.filter(parent=node).order_by(*self._ordering())

    def descendants(
        self, node_or_ids: Any, include_self: bool = False, max_depth: int | None = None
    ) -> Self:
        """Every node below ``node_or_ids``, as a lazy queryset (one statement when evaluated).

        ``node_or_ids`` is a row, a key, an iterable of either or a queryset
        of the model. ``include_self=True`` keeps the starting nodes, and
        ``max_depth=1`` stops at the children. The rows come unordered.
        """
        from django.core.exceptions import EmptyResultSet
        from django.db import connections
        from django.db.models.expressions import RawSQL

        from karni.tree import compile_queryset, start_from, walk_sql

        connection = connections[self.db]
        start = start_from(self.model, node_or_ids, connection)
        if start is None:
            return self.none()
        try:
            restrict = compile_queryset(self)
        except EmptyResultSet:
            return self.none()
        sql, params = walk_sql(
            self.model,
            connection,
            start=start,
            restrict=restrict,
            max_depth=max_depth,
            include_self=include_self,
        )
        return self.filter(pk__in=RawSQL(sql, params))

    def walk(
        self,
        nodes: Any,
        *,
        up: bool = False,
        include_self: bool = False,
        max_depth: int | None = None,
        limit: int | None = None,
    ) -> list[tuple[Any, Any, int]]:
        """``(key, parent key, depth)`` of each node of one walk, nearest first. Runs now.

        Down from ``nodes`` (``up=False``) or up to the root (``up=True``),
        through the rows of this queryset, ``depth`` counting the steps from
        the start (0 for a starting node, kept with ``include_self=True``).
        ``limit`` caps the rows. A node reached twice (two starting nodes on
        one branch) is listed once, at its smallest depth.
        """
        from django.core.exceptions import EmptyResultSet
        from django.db import connections

        from karni.tree import compile_queryset, start_from, walk_sql

        connection = connections[self.db]
        start = start_from(self.model, nodes, connection)
        if start is None:
            return []
        try:
            restrict = compile_queryset(self)
        except EmptyResultSet:
            return []
        order_limit = "ORDER BY depth"
        limit_params: list[Any] = []
        if limit is not None:
            order_limit += " LIMIT %s"
            limit_params = [int(limit)]
        sql, params = walk_sql(
            self.model,
            connection,
            start=start,
            up=up,
            restrict=restrict,
            max_depth=max_depth,
            include_self=include_self,
            select="node_id, parent_id, depth",
            order_limit=order_limit,
        )
        with connection.cursor() as cursor:
            cursor.execute(sql, [*params, *limit_params])
            fetched = cursor.fetchall()
        from karni.tree import pk_field

        pk = pk_field(self.model)
        rows: list[tuple[Any, Any, int]] = []
        seen: set[Any] = set()
        for key, parent, depth in fetched:
            key = pk.to_python(key)
            if key in seen:
                continue
            seen.add(key)
            rows.append((key, None if parent is None else pk.to_python(parent), int(depth)))
        return rows

    def ancestors(self, node: Any, include_self: bool = False) -> Self:
        """The nodes above ``node``, root first. Runs the walk now, the rows when evaluated.

        ``include_self=True`` ends the list with ``node``. A soft-deleted
        ancestor (or one this queryset filters out) ends the walk there.
        """
        from django.db.models import Case, IntegerField, Value, When

        rows = self.walk(node, up=True, include_self=include_self)
        if not rows:
            return self.none()
        keys = [key for key, _parent, _depth in sorted(rows, key=lambda row: -row[2])]
        order = Case(
            *(When(pk=key, then=Value(index)) for index, key in enumerate(keys)),
            output_field=IntegerField(),
        )
        return self.filter(pk__in=keys).order_by(order)

    def subtree_ids(self, ids: Any) -> set[Any]:
        """The keys of every node in the subtrees under ``ids``, those nodes included. Runs now.

        One query for any number of starting nodes, for a check such as
        "is this row inside a branch the user may see".
        """
        return {key for key, _parent, _depth in self.walk(ids, include_self=True)}


def _without_prefetch_cache(instance: models.Model) -> models.Model:
    """A shallow copy of ``instance`` with no ``prefetch_related`` results.

    A prefetch cache was filled through every scope. A related manager that
    lifts one must query past it, without touching the caller's instance.
    """
    clone = instance.__class__.__new__(instance.__class__)
    clone.__dict__.update(instance.__dict__)
    del clone.__dict__["_prefetched_objects_cache"]
    return clone


class ScopedManagerMixin:
    """Applies the named-scope pipeline (:mod:`karni.scopes`) to ``get_queryset()``.

    Mix it in ahead of a ``Manager.from_queryset(...)`` class. Django builds
    related managers (``parent.children``, M2M) and prefetch querysets by
    subclassing a model's default manager, so they run the pipeline too.
    They add their relation filter around it, and :meth:`without` keeps
    that relation filter.
    """

    #: Scope names this manager copy skips (set by :meth:`without`).
    _karni_lifted: frozenset[str] = frozenset()

    def get_queryset(self) -> Any:
        return apply_scopes(super().get_queryset(), lifted=self._karni_lifted)  # type: ignore[misc]

    def without(self, *names: str, reason: str) -> Any:
        """Every row the named scopes hide; every other scope still applies.

        ``Event.objects.without("soft_delete", reason="restore screen")``
        returns alive and soft-deleted events, and a tenant scope (when
        installed) still applies. ``reason`` is required and logged.
        Unknown names raise :class:`karni.scopes.UnknownScope`. On a related
        manager (``shelf.books.without(...)``) the relation filter stays, and
        prefetched results are read past.
        """
        lifted = registry.lift(self.model, names, reason)  # type: ignore[attr-defined]
        # Run the whole get_queryset() chain with only these scopes skipped.
        # A related manager adds its relation filter *around* this mixin.
        # Copying a manager is how Django's own db_manager() works.
        manager = copy.copy(self)
        manager._karni_lifted = self._karni_lifted | lifted
        instance = getattr(manager, "instance", None)
        if getattr(instance, "_prefetched_objects_cache", None):
            manager.instance = _without_prefetch_cache(instance)  # type: ignore[attr-defined]
        return manager.get_queryset()

    def all_with_deleted(self) -> Any:
        """Deprecated: use ``objects.without("soft_delete", reason=...)``."""
        warn_deprecated(
            "objects.all_with_deleted()",
            _LIFT_SOFT_DELETE,
            removed_in=_REMOVED_IN,
            doc_anchor="migrations/0.2.md#all_with_deleted",
        )
        return self.without(SOFT_DELETE, reason="all_with_deleted() (deprecated alias)")

    def deleted_only(self) -> Any:
        """Deprecated: use ``objects.without("soft_delete", reason=...).dead()``."""
        warn_deprecated(
            "objects.deleted_only()",
            'objects.without("soft_delete", reason=...).dead()',
            removed_in=_REMOVED_IN,
            doc_anchor="migrations/0.2.md#deleted_only",
        )
        return self.without(SOFT_DELETE, reason="deleted_only() (deprecated alias)").dead()


class SoftDeleteManager(ScopedManagerMixin, models.Manager.from_queryset(SoftDeleteQuerySet)):  # type: ignore[misc]
    """Default manager of :class:`karni.models.SoftDeleteModel`."""


class BaseManager(ScopedManagerMixin, models.Manager.from_queryset(BaseQuerySet)):  # type: ignore[misc]
    """Default manager of :class:`karni.models.BaseModel`."""


class TreeManager(ScopedManagerMixin, models.Manager.from_queryset(TreeQuerySet)):  # type: ignore[misc]
    """Experimental. Default manager of :class:`karni.models.TreeModel` (:class:`TreeQuerySet`)."""


# deprecated aliases (removed in 1.0)


class _DeprecatedAllObjectsDescriptor(ManagerDescriptor):
    """``Model.all_objects``: resolves the manager, then warns."""

    def __get__(self, instance: Any, cls: Any = None) -> Any:
        manager = super().__get__(instance, cls)
        warn_deprecated(
            f"{cls.__name__}.all_objects",
            f"{cls.__name__}.{_LIFT_SOFT_DELETE}",
            removed_in=_REMOVED_IN,
            doc_anchor="migrations/0.2.md#all_objects",
        )
        return manager


class _AllObjectsMixin:
    """The deprecated ``all_objects``: the default manager with ``soft_delete`` lifted.

    It used to be a plain manager that dropped every filter. It now lifts
    only ``soft_delete``, so it can never leak across a future tenant scope.
    """

    _karni_lifted = frozenset({SOFT_DELETE})

    def contribute_to_class(self, cls: Any, name: str) -> None:
        super().contribute_to_class(cls, name)  # type: ignore[misc]
        setattr(cls, name, _DeprecatedAllObjectsDescriptor(self))


class _SoftDeleteAllObjectsManager(_AllObjectsMixin, SoftDeleteManager):
    """``SoftDeleteModel.all_objects`` (deprecated)."""


class _BaseAllObjectsManager(_AllObjectsMixin, BaseManager):
    """``BaseModel.all_objects`` (deprecated)."""


def __getattr__(name: str) -> Any:
    if name == "SoftDeleteManagerMixin":
        warn_deprecated(
            "karni.managers.SoftDeleteManagerMixin",
            "karni.managers.ScopedManagerMixin",
            removed_in=_REMOVED_IN,
            doc_anchor="migrations/0.2.md#softdeletemanagermixin",
        )
        return ScopedManagerMixin
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
