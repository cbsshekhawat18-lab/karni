"""Composable querysets and managers behind Karni's model mixins.

Each model mixin in :mod:`karni.models` has a matching queryset here, and
they all extend :class:`KarniQuerySet`, so any combination composes by plain
multiple inheritance — ``BaseQuerySet`` is just the four stacked. Chaining
works across them: ``Event.objects.created_since(t).created_by(u).dead()``.

Override / escape hatch: subclass any queryset, build a manager with
``YourManager = SoftDeleteManagerMixin + Manager.from_queryset(YourQuerySet)``
(see :class:`BaseManager`) and redeclare ``objects`` on your model.
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import TYPE_CHECKING, Any, Self

from django.db import models
from django.utils import timezone

if TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser

__all__ = [
    "AuditedQuerySet",
    "BaseManager",
    "BaseQuerySet",
    "KarniQuerySet",
    "SoftDeleteManager",
    "SoftDeleteManagerMixin",
    "SoftDeleteQuerySet",
    "TimestampedQuerySet",
]


class KarniQuerySet(models.QuerySet):
    """Root of every Karni queryset: filters valid on any model."""

    def by_ids(self, ids: Any) -> Self:
        """Rows whose primary key is in ``ids`` (any iterable)."""
        return self.filter(pk__in=list(ids))


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
        return models.QuerySet.delete(self)

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


class SoftDeleteManagerMixin:
    """Hides soft-deleted rows; adds ``all_with_deleted()`` / ``deleted_only()``.

    Mix in ahead of a ``Manager.from_queryset(...)`` class whose queryset has
    a ``deleted_at`` filterable field. Both helpers keep every other filter
    the manager applies — on a related manager (``parent.children``, M2M) they
    stay scoped to that relation.
    """

    #: Set on a copy of the manager by :meth:`all_with_deleted`.
    _karni_include_deleted: bool = False

    def get_queryset(self) -> Any:
        queryset = super().get_queryset()  # type: ignore[misc]
        if self._karni_include_deleted:
            return queryset
        return queryset.filter(deleted_at__isnull=True)

    def all_with_deleted(self) -> Any:
        """Every row, soft-deleted or not (its ``delete()`` is still soft)."""
        # Run the whole get_queryset() chain (a related manager adds its
        # relation filter *around* this mixin) with only the alive filter
        # off; copying a manager is how Django's own db_manager() works.
        manager = copy.copy(self)
        manager._karni_include_deleted = True
        return manager.get_queryset()

    def deleted_only(self) -> Any:
        """Only soft-deleted rows."""
        return self.all_with_deleted().filter(deleted_at__isnull=False)


class SoftDeleteManager(SoftDeleteManagerMixin, models.Manager.from_queryset(SoftDeleteQuerySet)):  # type: ignore[misc]
    """Default manager of :class:`karni.models.SoftDeleteModel`."""


class BaseManager(SoftDeleteManagerMixin, models.Manager.from_queryset(BaseQuerySet)):  # type: ignore[misc]
    """Default manager of :class:`karni.models.BaseModel`."""
