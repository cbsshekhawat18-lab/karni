"""Karni model primitives.

Every Karni model — in ``karni.*`` apps and in projects built on Karni —
inherits :class:`BaseModel`: a UUID primary key plus ``created_at`` /
``updated_at`` audit timestamps. Models that must never lose rows inherit
:class:`SoftDeleteModel` instead, which turns ``delete()`` into a timestamp
flip and keeps hard deletion available as an explicit ``hard_delete()``.

Override / escape hatch: both bases are abstract — projects subclass them
freely, add fields, override managers (declare your own ``objects``) or
methods, and may skip them entirely for models that want Django's stock
behaviour. Nothing in Karni requires a model to inherit these classes.
"""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.db import models
from django.utils import timezone

__all__ = [
    "BaseModel",
    "SoftDeleteManager",
    "SoftDeleteModel",
    "SoftDeleteQuerySet",
]


class BaseModel(models.Model):
    """Abstract base for every Karni model.

    Provides a random UUID primary key (safe to expose in URLs and APIs, no
    sequential enumeration) and indexed ``created_at`` / ``updated_at`` audit
    timestamps. ``id``, ``created_at`` and ``updated_at`` are treated as
    read-only by Karni's serializer generation and as audit fields by the
    derived admin.

    Override / escape hatch: subclass and add fields as usual; redeclare a
    field (e.g. a different primary key) to replace it, or don't inherit
    ``BaseModel`` at all for models that want Django defaults. Note that
    changing these base fields in a project ripples migrations into every
    model that inherits them, including a swapped user model.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    """QuerySet whose ``delete()`` soft-deletes by stamping ``deleted_at``.

    Hard deletion never happens implicitly: it is only ever the explicit
    :meth:`hard_delete`. Both methods are ``queryset_only`` so neither is
    copied onto managers — ``Model.objects.delete()`` does not exist; you must
    build a queryset first (``Model.objects.all().delete()``), keeping bulk
    deletion deliberate.

    Override / escape hatch: subclass this queryset (and a matching manager
    via ``Manager.from_queryset``) and redeclare ``objects`` /
    ``all_objects`` on your model to change any of this behaviour.
    """

    def delete(self) -> tuple[int, dict[str, int]]:
        """Soft-delete every row in the queryset.

        Sets ``deleted_at`` to now with a single ``UPDATE`` and returns a
        Django-style ``(count, {model_label: count})`` tuple. Unlike a real
        delete this sends no ``pre_delete``/``post_delete`` signals, does not
        cascade to related objects, and (being a bulk ``update()``) does not
        refresh ``updated_at``.
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

    def alive(self) -> SoftDeleteQuerySet:
        """Only rows that are not soft-deleted."""
        return self.filter(deleted_at__isnull=True)

    def dead(self) -> SoftDeleteQuerySet:
        """Only rows that are soft-deleted."""
        return self.filter(deleted_at__isnull=False)


_SoftDeleteManagerBase = models.Manager.from_queryset(SoftDeleteQuerySet)


class SoftDeleteManager(_SoftDeleteManagerBase):
    """Manager that hides soft-deleted rows from every query.

    Bound as ``objects`` (and as the default manager) on
    :class:`SoftDeleteModel`, so ordinary queries — including related
    descriptors like ``parent.children.all()`` — never see deleted rows. Use
    the model's ``all_objects`` manager to reach them.

    Neither this manager nor ``all_objects`` sets ``use_in_migrations``, so
    swapping them in a subclass never touches migration state.
    """

    def get_queryset(self) -> SoftDeleteQuerySet:
        """Return the base queryset with soft-deleted rows filtered out."""
        queryset: SoftDeleteQuerySet = super().get_queryset()
        return queryset.filter(deleted_at__isnull=True)


class SoftDeleteModel(BaseModel):
    """Abstract base for models whose rows are soft-deleted.

    ``delete()`` (instance and queryset) stamps ``deleted_at`` instead of
    removing the row; ``objects`` hides deleted rows while ``all_objects``
    sees everything — though its ``delete()`` is *still* soft. Hard deletion
    is only ever the explicit :meth:`hard_delete` /
    ``queryset.hard_delete()``.

    Semantics to be aware of (all deliberate):

    * Soft deletes send no ``pre_delete``/``post_delete`` signals and do not
      cascade — related rows are untouched.
    * Hard deletes are real Django deletes: signals fire and cascades run,
      including over soft-deleted children.
    * Related descriptors hide deleted rows (``Meta.default_manager_name`` is
      ``"objects"``), but direct foreign-key access (``child.parent``) still
      resolves a soft-deleted target — Django's base manager is unfiltered so
      existing references keep working.

    Override / escape hatch: redeclare ``objects``/``all_objects`` with your
    own manager classes, or override ``delete``/``hard_delete``/``restore``.
    When declaring your own ``Meta``, subclass ``SoftDeleteModel.Meta`` to
    keep ``default_manager_name`` (and with it deleted-row hiding on related
    descriptors).
    """

    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects: ClassVar[SoftDeleteManager] = SoftDeleteManager()
    all_objects: ClassVar[models.Manager] = _SoftDeleteManagerBase()

    class Meta(BaseModel.Meta):
        abstract = True
        default_manager_name = "objects"

    @property
    def is_deleted(self) -> bool:
        """Whether this row is currently soft-deleted."""
        return self.deleted_at is not None

    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Soft-delete this row (stamp ``deleted_at`` and save).

        Keeps Django's ``delete(using=None, keep_parents=False)`` signature so
        callers (including the admin) need no special-casing; ``keep_parents``
        is accepted but irrelevant since nothing cascades. Sends no deletion
        signals. Returns a Django-style ``(1, {model_label: 1})`` tuple.
        """
        self.deleted_at = timezone.now()
        self.save(using=using, update_fields=["deleted_at", "updated_at"])
        return 1, {self._meta.label: 1}

    delete.alters_data = True  # type: ignore[attr-defined]

    def hard_delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Really delete this row via ``Model.delete`` — signals fire, cascades run."""
        return models.Model.delete(self, using=using, keep_parents=keep_parents)

    hard_delete.alters_data = True  # type: ignore[attr-defined]

    def restore(self, using: str | None = None) -> None:
        """Un-delete this row (clear ``deleted_at`` and save)."""
        self.deleted_at = None
        self.save(using=using, update_fields=["deleted_at", "updated_at"])

    restore.alters_data = True  # type: ignore[attr-defined]
