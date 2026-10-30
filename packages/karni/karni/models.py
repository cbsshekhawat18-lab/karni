"""Karni model primitives.

Four independent abstract mixins, each usable on its own, and
:class:`BaseModel` combining all of them — the base every project model
inherits:

* :class:`UUIDModel` — random UUID primary key (no sequential enumeration).
* :class:`IntegerKeyModel` — a 64-bit auto-incrementing integer primary key
  instead (experimental). :class:`BigIntBaseModel` is :class:`BaseModel` with
  it: the key type shows in each model's class line, so one project can mix
  both.
* :class:`TimestampedModel` — ``created_at`` / ``updated_at``.
* :class:`SoftDeleteModel` — ``deleted_at``; ``delete()`` hides instead of
  removing, the default manager excludes deleted rows (the ``soft_delete``
  scope, :mod:`karni.scopes`), and
  ``objects.without("soft_delete", reason=...)`` reaches them.
* :class:`AuditedModel` — ``created_by`` / ``updated_by``, stamped from
  :func:`karni.middleware.get_current_user` (contextvars; WSGI and ASGI).
* :class:`TreeModel` / :class:`OrderedTreeModel` — a ``parent`` hierarchy
  with cycle-safe walks (experimental). List it before the base:
  ``class Region(TreeModel, BaseModel)``.

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
    TreeManager,
    _BaseAllObjectsManager,
    _SoftDeleteAllObjectsManager,
)
from karni.middleware import get_current_user
from karni.signals import pre_write

__all__ = [
    "AuditedModel",
    "BaseModel",
    "BigIntBaseModel",
    "GuardedModel",
    "IntegerKeyModel",
    "OrderedTreeModel",
    "SoftDeleteManager",
    "SoftDeleteModel",
    "SoftDeleteQuerySet",
    "TimestampedModel",
    "TreeModel",
    "UUIDModel",
]


def _with_field(update_fields: Any, *names: str) -> Any:
    """Add ``names`` to a ``save(update_fields=...)`` value (``None`` stays ``None``)."""
    if update_fields is None:
        return None
    return {*update_fields, *names}


class UUIDModel(models.Model):
    """Random UUID primary key, safe to expose in URLs (no enumeration)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class IntegerKeyModel(models.Model):
    """Experimental. A 64-bit auto-incrementing integer primary key (``BigAutoField``).

    The database numbers rows 1, 2, 3, ..., so a key is short and sorts by
    insertion, and it can be guessed: a public detail URL lets anyone walk
    the table, which ``karni.W530`` reports. Ids stay JSON numbers, exact in
    JavaScript up to 2**53 - 1 and in a spreadsheet up to 15 digits.
    :class:`BigIntBaseModel` combines it with the other mixins.

    Override / escape hatch: redeclare ``id`` (an ``AutoField``, or a
    ``UUIDField`` again) on the subclass.
    """

    id = models.BigAutoField(primary_key=True)

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


class _KarniModel(GuardedModel, TimestampedModel, SoftDeleteModel, AuditedModel):
    """Everything :class:`BaseModel` and :class:`BigIntBaseModel` share, except the key.

    The mixin list, the managers, ``Meta`` and the ``pre_write`` signal are
    defined here once, so the two bases differ only in their ``id``. Private:
    inherit one of the two bases.
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


class BaseModel(_KarniModel, UUIDModel):
    """The base every Karni project model inherits: all four mixins (plus :class:`GuardedModel`).

    UUID primary key, timestamps, soft delete and audit users. ``id``,
    ``created_at``, ``updated_at``, ``created_by``, ``updated_by`` and
    ``deleted_at`` are read-only to Karni's generated serializers and audit
    fields to the derived admin; ``deleted_at`` is not exposed by the API.

    Override / escape hatch: subclass and add fields; redeclare a field to
    replace it; or compose the individual mixins instead. Changing these base
    fields ripples migrations into every inheriting model, including a
    swapped user model. :class:`BigIntBaseModel` is the same with an integer
    key.

    Every ``save()`` and ``delete()`` first sends :data:`karni.signals.pre_write`
    (``action`` ``create`` / ``update`` / ``delete``); a receiver that raises
    :class:`karni.exceptions.KarniWriteDeferred` stops the write before any
    SQL — how ``karni-approvals`` holds a change for a second person.
    """

    class Meta(_KarniModel.Meta):
        abstract = True


class BigIntBaseModel(_KarniModel, IntegerKeyModel):
    """Experimental. :class:`BaseModel` with a 64-bit integer key (:class:`IntegerKeyModel`).

    Everything else is the same: timestamps, soft delete, audit users, the
    guards, the managers and ``pre_write``. Choose it per model, in the class
    line (``class Reading(BigIntBaseModel)``), for a table that grows large,
    is joined a lot or meets other systems' integer ids. Karni's own models
    keep their UUIDs, and one project can mix both bases. Integer keys can be
    guessed, so a resource anyone may read is reported by ``karni.W530``.

    Override / escape hatch: the same as :class:`BaseModel`. Switching an
    existing model's key type while it holds data is a data migration Karni
    does not write for you.
    """

    class Meta(_KarniModel.Meta):
        abstract = True


# trees (experimental)

#: ``_karni_tree_loaded_parent`` before a row is loaded: the parent it had is unknown.
_UNKNOWN: Any = object()


class _AppendPosition(int):
    """The default ``position`` of :class:`OrderedTreeModel`: "after the last sibling".

    It is the integer 0 (what a migration writes and ``bulk_create`` stores), but
    ``save()`` can tell it from an explicit 0 and places the new node last.
    """


_APPEND = _AppendPosition(0)


def _key(model: type[models.Model], value: Any) -> Any:
    """The primary key ``value`` names (a row or a key), as the key field's Python value."""
    if isinstance(value, models.Model):
        value = value.pk
    if value is None:
        return None
    from karni.tree import pk_field

    return pk_field(model).to_python(value)


class TreeModel(models.Model):
    """Experimental. A node of a hierarchy: ``parent`` points at another row of the same model.

    List it before the base, ``class Region(TreeModel, BaseModel)`` (or
    ``BigIntBaseModel``), so ``objects`` is a :class:`karni.managers.TreeManager`
    (``karni.E344`` reports the other order). It adds:

    * ``parent``: a nullable foreign key to the model itself, ``PROTECT`` on
      delete, ``related_name="children"``, indexed. A node without a parent
      is a root.
    * the walks on ``objects``: ``roots()``, ``children(node)``,
      ``ancestors(node)``, ``descendants(nodes)`` and ``subtree_ids(ids)``,
      each one cycle-safe statement (:mod:`karni.tree`).
    * ``save()`` refuses a parent that is the node itself or one of its
      descendants (``E340``), and so do ``clean()`` (a form error on
      ``parent``) and :meth:`move_to`.
    * soft delete hides a branch: ``delete()`` refuses a node that still has
      live children (``E341``, HTTP 409), and :meth:`delete_branch` deletes
      the node and everything below it in one statement.

    Override / escape hatch: override :meth:`tree_ordering` for the sibling
    order, :meth:`check_parent` for the parent rule, or ``delete`` /
    :meth:`delete_branch`. Every walk is a method of
    :class:`karni.managers.TreeQuerySet`.
    """

    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
        db_index=True,
    )

    objects: ClassVar[TreeManager] = TreeManager()

    class Meta:
        abstract = True
        default_manager_name = "objects"

    @classmethod
    def tree_ordering(cls) -> tuple[Any, ...]:
        """The order of siblings: ``Meta.ordering``, else ``created_at`` then the key."""
        if cls._meta.ordering:
            return tuple(cls._meta.ordering)
        if any(field.name == "created_at" for field in cls._meta.concrete_fields):
            return ("created_at", "pk")
        return ("pk",)

    @classmethod
    def from_db(cls, db: str | None, field_names: Any, values: Any) -> Any:
        instance = super().from_db(db, field_names, values)
        loaded = instance.__dict__.get("parent_id", _UNKNOWN)
        instance.__dict__["_karni_tree_loaded_parent"] = loaded
        return instance

    def refresh_from_db(
        self, using: str | None = None, fields: Any = None, from_queryset: Any = None
    ) -> None:
        super().refresh_from_db(using=using, fields=fields, from_queryset=from_queryset)
        self.__dict__["_karni_tree_loaded_parent"] = self.__dict__.get("parent_id", _UNKNOWN)

    def check_parent(self, parent: Any = _UNKNOWN, using: str | None = None) -> None:
        """Raise :class:`karni.tree.TreeCycleError` (``E340``) when ``parent`` would close a cycle.

        ``parent`` (a row or a key, default: the current ``parent``) closes a
        cycle when it is this node or a node below it. The walk goes up from
        ``parent`` through every row, soft-deleted ones too, in one query. A
        new row has nothing below it, and an unchanged parent is not walked.
        """
        from django.db import connections

        from karni.tree import TreeCycleError, pk_field, start_from, walk_sql

        cls = type(self)
        current = parent is _UNKNOWN
        parent_key = _key(cls, self.parent_id if current else parent)  # type: ignore[attr-defined]
        if parent_key is None:
            return
        own = _key(cls, self.pk)
        if own is not None and parent_key == own:
            raise TreeCycleError(
                f"{cls.__name__} {own} cannot be its own parent. Choose another node, or no "
                "parent for a root."
            )
        if self._state.adding or own is None:
            return
        if current and self.__dict__.get("_karni_tree_loaded_parent", _UNKNOWN) == parent_key:
            return
        db = using or router.db_for_write(cls, instance=self)
        connection = connections[db]
        start = start_from(cls, [parent_key], connection)
        if start is None:
            return
        pk = pk_field(cls)
        sql, params = walk_sql(
            cls,
            connection,
            start=start,
            up=True,
            include_self=True,
            select="1",
            where="node_id = %s",
            where_params=[pk.get_db_prep_value(own, connection, prepared=False)],
            order_limit="LIMIT 1",
        )
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            closes = cursor.fetchone() is not None
        if closes:
            raise TreeCycleError(
                f"{cls.__name__} {parent_key} is below {cls.__name__} {own}, so it cannot become "
                "its parent: the tree would have a cycle. Move the other node first, or choose a "
                "parent outside this branch."
            )

    def clean(self) -> None:
        """Django's validation, plus the parent rule as a form error on ``parent``."""
        from karni.tree import TreeCycleError

        super().clean()
        try:
            self.check_parent()
        except TreeCycleError as exc:
            from django.core.exceptions import ValidationError

            raise ValidationError({"parent": [str(exc)]}, code=exc.code) from exc

    def save(self, *args: Any, **kwargs: Any) -> None:
        update_fields = kwargs.get("update_fields")
        if update_fields is None or {"parent", "parent_id"} & set(update_fields):
            checked = self.__dict__.pop("_karni_tree_checked", _UNKNOWN)
            if checked is _UNKNOWN or checked != _key(type(self), self.parent_id):  # type: ignore[attr-defined]
                self.check_parent(using=kwargs.get("using"))
        self._place_new_node(kwargs.get("using"))
        super().save(*args, **kwargs)
        self.__dict__["_karni_tree_loaded_parent"] = _key(type(self), self.parent_id)  # type: ignore[attr-defined]

    def _place_new_node(self, using: str | None) -> None:
        """Hook for :class:`OrderedTreeModel`: place a new node among its siblings."""

    def live_children_count(self, using: str | None = None) -> int:
        """How many children the default manager shows (live ones, under every scope)."""
        db = using or router.db_for_read(type(self), instance=self)
        return int(type(self)._default_manager.db_manager(db).filter(parent=self).count())

    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Delete this node, refused while it has live children (``E341``).

        A node with live children would hide them with it, so deleting one is
        a decision about the whole branch: :meth:`delete_branch`, or move the
        children first.
        """
        from karni.tree import TreeHasChildren

        count = self.live_children_count(using)
        if count:
            name = type(self).__name__
            raise TreeHasChildren(
                f"{name} {self.pk} has {count} live child node(s), and deleting it would hide "
                f"them. Move them to another parent first, or delete the whole branch with "
                f"delete_branch() (the API: DELETE with ?branch=true).",
                details={"children": count},
            )
        result: tuple[int, dict[str, int]] = super().delete(  # type: ignore[misc]
            using=using, keep_parents=keep_parents
        )
        return result

    delete.alters_data = True  # type: ignore[attr-defined]

    def delete_branch(self, using: str | None = None) -> int:
        """Delete this node and every live node below it in one statement; returns the count.

        On a soft-delete model every row gets the same ``deleted_at``, so the
        branch reads as one deletion. It sends ``pre_write`` (``action``
        ``"delete"``) for this node only, before any SQL, and like any bulk
        soft delete no deletion signals and no per-row history.
        """
        from karni.signals import pre_write

        pre_write.send(sender=type(self), instance=self, action="delete", update_fields=None)
        db = using or router.db_for_write(type(self), instance=self)
        branch = type(self)._default_manager.db_manager(db).descendants(self, include_self=True)
        count, _by_model = branch.delete()
        if hasattr(self, "deleted_at"):
            self.refresh_from_db(using=db, fields=["deleted_at"], from_queryset=None)
        return int(count)

    delete_branch.alters_data = True  # type: ignore[attr-defined]

    def move_to(self, parent: Any, position: int | None = None, using: str | None = None) -> None:
        """Give this node a new parent (a row, a key or ``None`` for a root) and save it.

        Refuses a parent below the node (``E340``). On an :class:`OrderedTreeModel`
        ``position`` places it among its new siblings (``None``: last) and the
        old and new siblings are renumbered from 0. Everything runs in one
        transaction. A ``position`` on an unordered tree is an error (``E343``).
        """
        from karni.exceptions import KarniValueError

        if position is not None and not isinstance(self, OrderedTreeModel):
            raise KarniValueError(
                f"{type(self).__name__} is a TreeModel, whose siblings have no order, so "
                "move_to() takes no position. Inherit OrderedTreeModel to order siblings.",
                code="E343",
            )
        if position is not None and (isinstance(position, bool) or int(position) < 0):
            raise KarniValueError(
                f"position must be a whole number from 0, not {position!r}.", code="E343"
            )
        cls = type(self)
        db = using or router.db_for_write(cls, instance=self)
        parent_key = _key(cls, parent)
        with transaction.atomic(using=db):
            self.check_parent(parent_key, using=db)
            old_parent = _key(cls, self.parent_id)  # type: ignore[attr-defined]
            if isinstance(parent, models.Model):
                self.parent = parent
            else:
                self.parent_id = parent_key  # type: ignore[attr-defined]
            self._renumber(old_parent, parent_key, position, db)
            self.__dict__["_karni_tree_checked"] = parent_key
            self.save(using=db)

    move_to.alters_data = True  # type: ignore[attr-defined]

    def _renumber(self, old_parent: Any, new_parent: Any, position: int | None, db: str) -> None:
        """Hook for :class:`OrderedTreeModel`: number the siblings after a move."""


class OrderedTreeModel(TreeModel):
    """Experimental. A :class:`TreeModel` whose siblings have an order: ``position``.

    Siblings sort by ``position`` (0 first), then ``created_at``, then the
    key. A node created without a position goes after its last sibling (one
    query on create), an explicit one is kept, and ``bulk_create`` stores 0.
    :meth:`move_to` takes a ``position`` and renumbers the old and the new
    siblings from 0 in the same transaction.

    Override / escape hatch: redeclare ``position``, or override
    :meth:`tree_ordering`.
    """

    position = models.PositiveIntegerField(default=_APPEND, db_index=True)

    class Meta(TreeModel.Meta):
        abstract = True

    @classmethod
    def tree_ordering(cls) -> tuple[Any, ...]:
        """``position``, then :meth:`TreeModel.tree_ordering`."""
        rest = tuple(name for name in super().tree_ordering() if name != "position")
        return ("position", *rest)

    def _place_new_node(self, using: str | None) -> None:
        if not (self._state.adding and type(self.position) is _AppendPosition):
            return
        db = using or router.db_for_write(type(self), instance=self)
        siblings = type(self)._default_manager.db_manager(db).filter(parent_id=self.parent_id)  # type: ignore[attr-defined]
        last = siblings.aggregate(last=models.Max("position"))["last"]
        self.position = 0 if last is None else int(last) + 1

    def _renumber(self, old_parent: Any, new_parent: Any, position: int | None, db: str) -> None:
        manager = type(self)._default_manager.db_manager(db)
        ordering = self.tree_ordering()
        siblings = list(
            manager.filter(parent_id=new_parent).exclude(pk=self.pk).order_by(*ordering)
        )
        index = len(siblings) if position is None else min(int(position), len(siblings))
        changed: list[OrderedTreeModel] = []
        for number, node in enumerate([*siblings[:index], self, *siblings[index:]]):
            if node is self:
                self.position = number
            elif node.position != number:
                node.position = number
                changed.append(node)
        if old_parent != new_parent:
            left = manager.filter(parent_id=old_parent).exclude(pk=self.pk).order_by(*ordering)
            for number, node in enumerate(left):
                if node.position != number:
                    node.position = number
                    changed.append(node)
        if changed:
            manager.bulk_update(changed, ["position"])
