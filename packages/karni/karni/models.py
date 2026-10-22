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
from django.db import IntegrityError, models, router, transaction
from django.utils import timezone

# Connects karni.fields' class_prepared hook before any project model exists, so
# `class Karni: append_only` and LiveUniqueConstraint names apply to every model.
import karni.fields.base  # noqa: E402,F401,I001
from karni import constraints as _constraints  # noqa: F401 - connects class Karni: no_overlap
from karni import guards
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
from karni.signals import pre_write

__all__ = [
    "AuditedModel",
    "BaseModel",
    "GuardedModel",
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

    def _save_deleted_at(self, using: str | None, before: Any) -> None:
        fields = ["deleted_at"]
        if any(f.name == "updated_at" for f in self._meta.concrete_fields):
            fields.append("updated_at")
        # One transaction with the on_deleted / on_restored listeners: one that
        # refuses (a restore that would oversell) undoes the delete or restore,
        # and the instance keeps the deleted_at it had.
        try:
            with transaction.atomic(using=using or self._state.db):
                self.save(using=using, update_fields=fields)
        except BaseException:
            self.deleted_at = before
            raise

    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Soft-delete this row. Keeps Django's signature so callers need no special case."""
        before, self.deleted_at = self.deleted_at, timezone.now()
        self._save_deleted_at(using, before)
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
        """Un-delete this row (inside a transaction with the ``on_restored`` listeners)."""
        before, self.deleted_at = self.deleted_at, None
        self._save_deleted_at(using, before)

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


class GuardedModel(models.Model):
    """The model half of ``StateField``, ``CapacityField`` and ``no_overlap``.

    Adds no field. For a model that has any of them (others pay one cached
    lookup per save):

    * ``from_db()`` / ``refresh_from_db()`` remember what the row held, so a
      state change is checked from the loaded state, not a stale copy;
    * ``save()`` checks every state change before any SQL (``E980`` /
      ``E982``), runs the write in a transaction (a savepoint when nested),
      records transitions in the change log, sends
      ``karni.lifecycle.state_changed``, and turns an ``IntegrityError`` from
      a Karni constraint into a named error (``E984`` / ``E985``, HTTP 409);
    * ``_do_update()`` makes the ``UPDATE`` conditional on the loaded state
      (``AND "status" = 'draft'``): a concurrent transition makes it match
      nothing and raises ``StateConflict`` (``E981``) instead of overwriting;
    * ``transition(field, to, **values)`` / ``allowed_transitions(field)``.

    :class:`BaseModel` includes it. Override / escape hatch: override any of
    these methods; :mod:`karni.guards` holds the engine.
    """

    class Meta:
        abstract = True

    @classmethod
    def from_db(cls, db: str | None, field_names: Any, values: Any) -> Any:
        instance = super().from_db(db, field_names, values)
        guards.remember(instance)
        return instance

    def refresh_from_db(
        self, using: str | None = None, fields: Any = None, from_queryset: Any = None
    ) -> None:
        super().refresh_from_db(using=using, fields=fields, from_queryset=from_queryset)
        guards.remember(self, fields)

    def save(self, *args: Any, **kwargs: Any) -> None:
        plan = guards.plan_write(self, kwargs.get("update_fields"))
        if plan is None:
            super().save(*args, **kwargs)
            return
        if plan.extra_fields and kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = {*kwargs["update_fields"], *plan.extra_fields}
        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        guards.begin(self, plan)
        try:
            self._guarded_write(using, plan, args, kwargs)
        except IntegrityError as exc:
            from karni.conflicts import translate

            error = translate(exc, instance=self, using=using)
            if error is None or error is exc:
                raise
            raise error from exc
        finally:
            guards.end(self)

    def _guarded_write(self, using: str, plan: Any, args: Any, kwargs: Any) -> None:
        """The write and its bookkeeping in one savepoint, after the no-overlap locks."""
        from karni.constraints import lock_overlap_resources

        with transaction.atomic(using=using):
            lock_overlap_resources(self, using)
            super().save(*args, **kwargs)
            guards.after_write(self, plan, using)

    def _do_update(
        self,
        base_qs: Any,
        using: Any,
        pk_val: Any,
        values: Any,
        update_fields: Any,
        forced_update: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        expected = guards.expected_states(self, values)
        if expected:
            base_qs = base_qs.filter(**expected)
        updated = super()._do_update(
            base_qs, using, pk_val, values, update_fields, forced_update, *args, **kwargs
        )
        if expected and not updated:
            conflict = guards.state_moved(
                self, base_qs.model._base_manager.using(using), pk_val, expected
            )
            if conflict is not None:
                raise conflict
        return updated

    def transition(self, field: str, to: Any, **values: Any) -> None:
        """Move ``field`` to ``to`` and save it (:func:`karni.lifecycle.transition`)."""
        from karni.lifecycle import transition

        transition(self, field, to, **values)

    transition.alters_data = True  # type: ignore[attr-defined]

    def allowed_transitions(self, field: str) -> tuple[str, ...]:
        """The states ``field`` may move to from its loaded state."""
        from karni.lifecycle import allowed_transitions

        return allowed_transitions(self, field)


class BaseModel(GuardedModel, UUIDModel, TimestampedModel, SoftDeleteModel, AuditedModel):
    """The base every Karni project model inherits: all four mixins (plus :class:`GuardedModel`).

    UUID primary key, timestamps, soft delete and audit users. ``id``,
    ``created_at``, ``updated_at``, ``created_by``, ``updated_by`` and
    ``deleted_at`` are read-only to Karni's generated serializers and audit
    fields to the derived admin; ``deleted_at`` is not exposed by the API.

    Override / escape hatch: subclass and add fields; redeclare a field to
    replace it; or compose the individual mixins instead. Changing these base
    fields ripples migrations into every inheriting model, including a
    swapped user model.

    Every ``save()`` and ``delete()`` first sends :data:`karni.signals.pre_write`
    (``action`` ``create`` / ``update`` / ``delete``); a receiver that raises
    :class:`karni.exceptions.KarniWriteDeferred` stops the write before any
    SQL — how ``karni-approvals`` holds a change for a second person.
    """

    objects: ClassVar[BaseManager] = BaseManager()
    #: Deprecated since 0.2, removed in 1.0: ``objects.without("soft_delete", reason=...)``.
    all_objects: ClassVar[BaseManager] = _BaseAllObjectsManager()

    class Meta(SoftDeleteModel.Meta):
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not getattr(self, "_karni_in_delete", False):
            # An illegal state change is refused before anyone may defer it.
            guards.plan_write(self, kwargs.get("update_fields"))
            pre_write.send(
                sender=type(self),
                instance=self,
                action="create" if self._state.adding else "update",
                update_fields=kwargs.get("update_fields"),
            )
        super().save(*args, **kwargs)

    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Soft-delete after ``pre_write`` (sent once: not again for the ``deleted_at`` save)."""
        pre_write.send(sender=type(self), instance=self, action="delete", update_fields=None)
        self._karni_in_delete = True
        try:
            return super().delete(using=using, keep_parents=keep_parents)
        finally:
            self._karni_in_delete = False

    delete.alters_data = True  # type: ignore[attr-defined]
