"""Karni model primitives.

Four independent abstract mixins, each usable on its own, and
:class:`BaseModel` combining all of them — the base every project model
inherits:

* :class:`UUIDModel` — random UUID primary key (no sequential enumeration).
* :class:`TimestampedModel` — ``created_at`` / ``updated_at``.
* :class:`SoftDeleteModel` — ``deleted_at``; ``delete()`` hides instead of
  removing, the default manager excludes deleted rows (the ``soft_delete``
  scope, :mod:`karni.scopes`), and
  ``objects.without("soft_delete", reason=...)`` reaches them.
* :class:`AuditedModel` — ``created_by`` / ``updated_by``, stamped from
  :func:`karni.middleware.get_current_user` (contextvars; WSGI and ASGI).

Override / escape hatch: every class is abstract — subclass, redeclare a
field or manager, or compose only the mixins you want (``class Log(
UUIDModel, TimestampedModel)`` for an append-only table that must never be
soft-deleted). Nothing in Karni requires a model to inherit these classes.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from django.conf import settings
from django.db import models
from django.utils import timezone

from karni.managers import (
    AuditedQuerySet,
    BaseManager,
    SoftDeleteManager,
    SoftDeleteQuerySet,
    TimestampedQuerySet,
    _BaseAllObjectsManager,
    _SoftDeleteAllObjectsManager,
)
from karni.middleware import get_current_user

__all__ = [
    "AuditedModel",
    "BaseModel",
    "SoftDeleteManager",
    "SoftDeleteModel",
    "SoftDeleteQuerySet",
    "TimestampedModel",
    "UUIDModel",
]


def _with_field(update_fields: Any, *names: str) -> Any:
    """Add ``names`` to a ``save(update_fields=...)`` value (``None`` stays ``None``)."""
    if update_fields is None:
        return None
    return {*update_fields, *names}


class UUIDModel(models.Model):
    """Random UUID primary key — safe to expose in URLs, no enumeration."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimestampedModel(models.Model):
    """``created_at`` (indexed) and ``updated_at``, maintained by Django.

    ``updated_at`` uses ``auto_now``: bulk ``QuerySet.update()`` does not
    refresh it — set it explicitly in bulk updates that should count.
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects: ClassVar[models.Manager] = models.Manager.from_queryset(TimestampedQuerySet)()

    class Meta:
        abstract = True


class SoftDeleteModel(models.Model):
    """Rows are hidden by ``delete()`` instead of removed.

    * ``objects`` (the default manager) excludes deleted rows through the
      ``soft_delete`` scope, and so do related descriptors like
      ``parent.children.all()``, prefetches and the admin.
    * ``objects.without("soft_delete", reason=...)`` reaches them (add
      ``.dead()`` for deleted rows only) and keeps every other scope.
    * ``delete()`` (instance and queryset) stamps ``deleted_at``; ``restore()``
      clears it; ``hard_delete()`` is the only real deletion and runs Django's
      normal cascade, including over soft-deleted children.
    * Soft deletes send no deletion signals and do not cascade; a child's FK
      to a soft-deleted parent still resolves (the base manager is unfiltered),
      so existing references never break.

    Override / escape hatch: redeclare ``objects`` with your own manager built
    on :class:`karni.managers.ScopedManagerMixin` (system check karni.E001
    rejects one that is not), or override ``delete``/``hard_delete``/``restore``.
    When declaring your own ``Meta``, subclass ``SoftDeleteModel.Meta`` to keep
    ``default_manager_name`` (and with it deleted-row hiding on relations).
    """

    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True, editable=False)

    objects: ClassVar[SoftDeleteManager] = SoftDeleteManager()
    #: Deprecated since 0.2, removed in 1.0: ``objects.without("soft_delete", reason=...)``.
    all_objects: ClassVar[SoftDeleteManager] = _SoftDeleteAllObjectsManager()

    class Meta:
        abstract = True
        default_manager_name = "objects"

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def _save_deleted_at(self, using: str | None) -> None:
        fields = ["deleted_at"]
        if any(f.name == "updated_at" for f in self._meta.concrete_fields):
            fields.append("updated_at")
        self.save(using=using, update_fields=fields)

    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Soft-delete this row. Keeps Django's signature so callers need no special case."""
        self.deleted_at = timezone.now()
        self._save_deleted_at(using)
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
        """Un-delete this row."""
        self.deleted_at = None
        self._save_deleted_at(using)

    restore.alters_data = True  # type: ignore[attr-defined]


class AuditedModel(models.Model):
    """``created_by`` / ``updated_by``, stamped from the current user on save.

    The user comes from :func:`karni.middleware.get_current_user` — set by
    ``CurrentUserMiddleware`` during requests, or explicitly with
    ``karni.middleware.current_user(user)`` in tasks and commands. With no
    current user nothing is stamped (an existing ``created_by`` is never
    cleared). Both FKs are nullable, ``SET_NULL`` on user deletion, and have
    no reverse accessor (``related_name="+"``) — query with
    ``Model.objects.created_by(user)``.
    """

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    objects: ClassVar[models.Manager] = models.Manager.from_queryset(AuditedQuerySet)()

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        user = get_current_user()
        if user is not None:
            if self._state.adding and self.created_by_id is None:
                self.created_by = user
            self.updated_by = user
            kwargs["update_fields"] = _with_field(kwargs.get("update_fields"), "updated_by")
        super().save(*args, **kwargs)


class BaseModel(UUIDModel, TimestampedModel, SoftDeleteModel, AuditedModel):
    """The base every Karni project model inherits: all four mixins.

    UUID primary key, timestamps, soft delete and audit users. ``id``,
    ``created_at``, ``updated_at``, ``created_by``, ``updated_by`` and
    ``deleted_at`` are read-only to Karni's generated serializers and audit
    fields to the derived admin; ``deleted_at`` is not exposed by the API.

    Override / escape hatch: subclass and add fields; redeclare a field to
    replace it; or compose the individual mixins instead. Changing these base
    fields ripples migrations into every inheriting model, including a
    swapped user model.
    """

    objects: ClassVar[BaseManager] = BaseManager()
    #: Deprecated since 0.2, removed in 1.0: ``objects.without("soft_delete", reason=...)``.
    all_objects: ClassVar[BaseManager] = _BaseAllObjectsManager()

    class Meta(SoftDeleteModel.Meta):
        abstract = True
