"""Model lifecycle listeners and queued (Celery) dispatch.

Put listeners in ``<app>/listeners.py``; Karni imports that module for every
installed app at startup (:func:`autodiscover`, called from
``KarniAppConfig.ready()``), so receivers connect without any
``AppConfig.ready()`` boilerplate::

    # shop/listeners.py
    from karni.events import on_created, on_deleted, on_updated

    from shop.models import Order


    @on_created(Order)
    def stamp_reference(order: Order) -> None:
        ...


    @on_updated(Order, queued=True)  # runs in a Celery worker after commit
    def sync_to_crm(order: Order) -> None:
        ...


    @on_deleted(Order)
    def release_stock(order: Order) -> None:
        ...

Semantics (each listener receives the model instance only):

* ``on_created`` — ``post_save`` with ``created=True``.
* ``on_updated`` — every other ``post_save``, *except* a soft delete. A
  ``restore()`` counts as an update.
* ``on_deleted`` — a **soft delete** (``SoftDeleteModel.delete()``, detected
  by :func:`is_soft_delete`) or a hard delete (``post_delete``) of a row that
  was still live. It fires once per row: purging an already soft-deleted row
  (``hard_delete()``) does not fire it again.
* ``on_restored`` — ``SoftDeleteModel.restore()`` (detected by
  :func:`is_restore`), inside the restore's transaction: raising undoes the
  restore. What a delete listener gave back, a restore listener takes again.
* Fixture loading (``raw=True`` saves) never fires a listener.
* Bulk operations that bypass ``save()``/``delete()`` — ``QuerySet.update()``,
  ``bulk_create``, and the soft ``QuerySet.delete()`` and ``QuerySet.restore()``
  of :class:`~karni.managers.SoftDeleteQuerySet` (one ``UPDATE``) — send no
  signals, exactly as in plain Django, so they fire nothing. Karni's admin
  deletes and restores row by row, so its actions do fire them.
* Like Django signals, the sender is the exact class: a listener on a parent
  model does not hear its subclasses or proxies.
* ``on_transition`` — a ``StateField`` moved along a declared transition
  (``karni.lifecycle.state_changed``), optionally only into ``to=`` or out of
  ``source=`` states. It fires after the row is written, inside the save's
  transaction, once per transition.

Plain listeners run inline, inside the caller's transaction. ``queued=True``
(or :func:`queued`) is Laravel's ``ShouldQueue``: the work is handed to a
Celery task **when the transaction commits** (``transaction.on_commit``), so
the worker always sees committed rows and a rolled-back save queues nothing.

Custom events are plain :class:`django.dispatch.Signal` objects declared in
``<app>/events.py`` (autodiscovered with the listeners) and received in
``<app>/listeners.py`` with ``@receiver`` — see ``docs/events.md``.

Override / escape hatches: plain ``@receiver(post_save, sender=...)`` keeps
working next to these helpers (use it when you need ``update_fields``,
``using`` or the raw signal kwargs); :func:`is_soft_delete` is public for such
receivers; set ``KARNI_EVENTS_AUTODISCOVER = False`` to stop the startup
import and import your listener modules yourself.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeVar, overload

from celery import shared_task
from django.apps import apps
from django.core import serializers
from django.core.exceptions import FieldDoesNotExist
from django.db import models, transaction
from django.db.models.signals import post_delete, post_save
from django.utils.module_loading import autodiscover_modules

from karni.celery import resolve_task
from karni.exceptions import KarniImproperlyConfigured, KarniTypeError

__all__ = [
    "AUTODISCOVER_MODULES",
    "QueuedListener",
    "autodiscover",
    "is_restore",
    "is_soft_delete",
    "on_created",
    "on_deleted",
    "on_restored",
    "on_transition",
    "on_updated",
    "queued",
]

logger = logging.getLogger(__name__)

#: Per-app modules imported at startup, in this order (events before the
#: listeners that usually import them).
AUTODISCOVER_MODULES: tuple[str, ...] = ("events", "listeners")

#: A model class, or a lazy ``"app_label.ModelName"`` reference.
ModelRef = type[models.Model] | str

F = TypeVar("F", bound=Callable[..., Any])

_SOFT_DELETE_FIELD = "deleted_at"


def autodiscover() -> None:
    """Import ``<app>.events`` then ``<app>.listeners`` for every installed app.

    Apps without those modules are skipped; an import error *inside* one
    propagates. Called by ``KarniAppConfig.ready()`` unless the
    ``KARNI_EVENTS_AUTODISCOVER`` setting is ``False``; idempotent (Python's
    import cache), so calling it again is harmless.
    """
    autodiscover_modules(*AUTODISCOVER_MODULES)


# soft-delete detection


def _has_soft_delete_field(instance: models.Model) -> bool:
    try:
        instance._meta.get_field(_SOFT_DELETE_FIELD)
    except FieldDoesNotExist:
        return False
    return True


def _is_soft_deleted(instance: models.Model) -> bool:
    """True when the instance has a ``deleted_at`` field that is set."""
    return _has_soft_delete_field(instance) and getattr(instance, _SOFT_DELETE_FIELD) is not None


def is_soft_delete(instance: models.Model, update_fields: Any) -> bool:
    """Whether a ``post_save`` is a soft delete.

    True when the save wrote ``deleted_at`` explicitly
    (``update_fields`` names it) and left it set — exactly what
    :meth:`karni.models.SoftDeleteModel.delete` does. A full ``save()`` of a
    row that happens to have ``deleted_at`` set is an update, not a delete.
    Public so plain ``@receiver(post_save)`` code can reuse the rule.
    """
    if update_fields is None or _SOFT_DELETE_FIELD not in update_fields:
        return False
    return _is_soft_deleted(instance)


def is_restore(instance: models.Model, update_fields: Any) -> bool:
    """Whether a ``post_save`` is a restore: the save wrote ``deleted_at`` and cleared it.

    Exactly what :meth:`karni.models.SoftDeleteModel.restore` does. Public,
    like :func:`is_soft_delete`, so plain receivers can reuse the rule.
    """
    if update_fields is None or _SOFT_DELETE_FIELD not in update_fields:
        return False
    return _has_soft_delete_field(instance) and getattr(instance, _SOFT_DELETE_FIELD) is None


# queued dispatch


def _portable_pk(pk: Any) -> Any:
    """Primary keys travel as int or str (UUIDs as strings) for any serializer."""
    return pk if isinstance(pk, int | str) else str(pk)


def _snapshot(instance: models.Model) -> str:
    """Concrete field values as Django-serializer JSON (no queries, no M2M)."""
    names = [field.name for field in instance._meta.concrete_fields]
    return serializers.serialize("json", [instance], fields=names)


def _load_instance(model_label: str, pk: Any, snapshot: str | None) -> models.Model | None:
    """Re-fetch the row (soft-deleted rows included), else rebuild it from ``snapshot``."""
    model = apps.get_model(model_label)
    instance: models.Model | None = model._base_manager.filter(pk=pk).first()
    if instance is None and snapshot is not None:
        restored = next(iter(serializers.deserialize("json", snapshot, ignorenonexistent=True)))
        instance = restored.object
    return instance


def _dotted_name(func: Callable[..., Any]) -> str:
    """``module.qualname`` of a module-level function (the queued task's name)."""
    module = getattr(func, "__module__", None)
    qualname = getattr(func, "__qualname__", None)
    if not module or not qualname or "<" in qualname:
        raise KarniImproperlyConfigured(
            f"queued listener {func!r} must be a module-level function: the worker finds "
            "it by its dotted name. Define it at the top level of <app>/listeners.py, or "
            "queue an existing task with queued('app.tasks.task_name').",
            code="E401",
        )
    return f"{module}.{qualname}"


def _listener_task(func: Callable[[Any], Any], name: str) -> Any:
    """Register (once per name) the Celery task that runs ``func`` in a worker.

    The task is a ``shared_task`` named after the listener, so every Celery
    app — the worker's included, which imports ``<app>/listeners.py`` at
    Django startup — knows it.
    """

    def run(model_label: str, pk: Any, snapshot: str | None = None) -> None:
        instance = _load_instance(model_label, pk, snapshot)
        if instance is None:
            logger.warning(
                "karni.events: queued listener %s skipped because %s pk=%r no longer exists.",
                name,
                model_label,
                pk,
            )
            return
        func(instance)

    run.__module__ = func.__module__
    run.__qualname__ = run.__name__ = getattr(func, "__name__", "run")
    run.__doc__ = func.__doc__
    return shared_task(name=name)(run)


class QueuedListener:
    """A listener whose work runs in a Celery worker after the transaction commits.

    Built by :func:`queued` (or ``queued=True`` on the ``on_*`` decorators).
    Two shapes:

    * **function** — ``queued(func)``: ``func`` is registered as its own
      Celery task (named ``"<module>.<function>"``); the worker re-fetches the
      row by primary key — soft-deleted rows included — and calls
      ``func(instance)``. For a hard delete the row is gone, so a snapshot of
      its field values travels with the message and the worker rebuilds an
      unsaved instance from it. A row that vanished before the worker ran
      (created then hard-deleted) is skipped with a warning.
    * **task** — ``queued(task)`` / ``queued("app.tasks.name")``: an existing
      Celery task receives the row's primary key (UUIDs as strings).

    ``options`` are passed to ``apply_async`` (``queue=``, ``countdown=``,
    ``priority=`` …). Calling the listener directly also queues.
    """

    def __init__(self, target: Callable[[Any], Any] | str, **options: Any) -> None:
        self.options = options
        self.func: Callable[[Any], Any] | None
        self.task: Any
        if isinstance(target, str) or hasattr(target, "apply_async"):
            self.func = None
            self.task = target
            self.name = target if isinstance(target, str) else str(getattr(target, "name", target))
        else:
            self.func = target
            self.name = _dotted_name(target)
            self.task = _listener_task(target, self.name)

    def __repr__(self) -> str:
        return f"<QueuedListener {self.name}>"

    def __call__(self, instance: models.Model) -> None:
        self.dispatch(instance)

    def dispatch(
        self, instance: models.Model, *, using: str | None = None, snapshot: bool = False
    ) -> None:
        """Queue the work for ``instance`` on commit of the ``using`` connection.

        Everything the worker needs (model label, primary key, optional
        snapshot) is captured *now*: Django clears ``pk`` on deleted
        instances before commit callbacks run.
        """
        pk = _portable_pk(instance.pk)
        if self.func is None:
            args: tuple[Any, ...] = (pk,)
        else:
            args = (instance._meta.label, pk, _snapshot(instance) if snapshot else None)
        task_ref = self.task
        options = dict(self.options)

        def send() -> None:
            resolve_task(task_ref).apply_async(args=args, **options)

        transaction.on_commit(send, using=using or instance._state.db)


@overload
def queued(target: Callable[[Any], Any] | str, /, **options: Any) -> QueuedListener: ...


@overload
def queued(
    target: None = None, /, **options: Any
) -> Callable[[Callable[[Any], Any]], QueuedListener]: ...


def queued(
    target: Callable[[Any], Any] | str | None = None, /, **options: Any
) -> QueuedListener | Callable[[Callable[[Any], Any]], QueuedListener]:
    """Defer a listener to a Celery worker, dispatched on transaction commit.

    Three spellings::

        @on_created(Order)
        @queued                       # or @queued(queue="emails")
        def send_receipt(order): ...  # runs in the worker with the re-fetched row

        on_created(Order)(queued(tasks.send_receipt))      # existing task gets order.pk
        on_deleted(Order)(queued("shop.tasks.purge_files"))

    ``options`` go to ``apply_async``. See :class:`QueuedListener` for what
    the worker receives.
    """
    if target is None:

        def decorate(func: Callable[[Any], Any]) -> QueuedListener:
            return QueuedListener(func, **options)

        return decorate
    return QueuedListener(target, **options)


# lifecycle decorators


def _model_label(model: ModelRef) -> str:
    return model if isinstance(model, str) else model._meta.label


def _listener_id(listener: Any) -> str:
    if isinstance(listener, QueuedListener):
        return listener.name
    module = getattr(listener, "__module__", "?")
    return f"{module}.{getattr(listener, '__qualname__', repr(listener))}"


def _prepare(listener: Callable[[Any], Any], queued_: bool) -> Callable[[Any], Any]:
    if not callable(listener):
        raise KarniTypeError(
            f"karni.events: listener must be callable, got {listener!r}.", code="E402"
        )
    if queued_ and not isinstance(listener, QueuedListener):
        return QueuedListener(listener)
    return listener


def _invoke(
    listener: Callable[[Any], Any], instance: models.Model, using: str | None, snapshot: bool
) -> None:
    if isinstance(listener, QueuedListener):
        listener.dispatch(instance, using=using, snapshot=snapshot)
    else:
        listener(instance)


def on_created(model: ModelRef, *, queued: bool = False) -> Callable[[F], F]:
    """Run the decorated ``listener(instance)`` after a row of ``model`` is created.

    :param model: the model class, or ``"app_label.ModelName"`` (lazy).
    :param queued: hand the work to a Celery worker on commit (see :func:`queued`).
    :returns: a decorator returning the listener unchanged (still directly callable).
    """
    return _decorator("created", model, queued)


def on_updated(model: ModelRef, *, queued: bool = False) -> Callable[[F], F]:
    """Run the decorated ``listener(instance)`` after a row of ``model`` is updated.

    Every non-creating ``post_save`` except a soft delete; ``restore()`` is an
    update. Parameters as :func:`on_created`.
    """
    return _decorator("updated", model, queued)


def on_deleted(model: ModelRef, *, queued: bool = False) -> Callable[[F], F]:
    """Run the decorated ``listener(instance)`` after a row of ``model`` is deleted.

    Fires for a soft delete and for a hard delete of a live row — once per
    row: purging an already soft-deleted row does not fire again. Parameters
    as :func:`on_created`.
    """
    return _decorator("deleted", model, queued)


def on_restored(model: ModelRef, *, queued: bool = False) -> Callable[[F], F]:
    """Run the decorated ``listener(instance)`` after a soft-deleted row of ``model`` is restored.

    The counterpart of :func:`on_deleted`: what a delete gave back (seats,
    stock, a slot), a restore takes again. It runs inside the restore's
    transaction, so raising undoes the restore (``reserve()`` on a sold-out
    tier refuses it with E985). A restore is also an update, so
    :func:`on_updated` listeners hear it too. ``QuerySet.restore()`` is a bulk
    ``UPDATE`` and fires nothing, like ``QuerySet.delete()``; Karni's admin
    restores row by row. Parameters as :func:`on_created`.
    """
    return _decorator("restored", model, queued)


def _decorator(event: str, model: ModelRef, queued_: bool) -> Callable[[F], F]:
    if not isinstance(model, str) and not (
        isinstance(model, type) and issubclass(model, models.Model)
    ):
        raise KarniTypeError(
            f"karni.events.on_{event}() takes a model class or an 'app_label.ModelName' "
            f"string, got {model!r}.",
            code="E402",
        )

    def decorate(listener: F) -> F:
        _connect(event, model, _prepare(listener, queued_))
        return listener

    return decorate


def _connect(event: str, model: ModelRef, listener: Callable[[Any], Any]) -> None:
    uid = f"karni.events:{event}:{_model_label(model)}:{_listener_id(listener)}"

    if event == "created":

        def on_create(sender: Any, instance: Any, created: bool = False, **kw: Any) -> None:
            if created and not kw.get("raw"):
                _invoke(listener, instance, kw.get("using"), snapshot=False)

        post_save.connect(on_create, sender=model, weak=False, dispatch_uid=uid)
        return

    if event == "restored":

        def on_restore(sender: Any, instance: Any, created: bool = False, **kw: Any) -> None:
            if created or kw.get("raw") or not is_restore(instance, kw.get("update_fields")):
                return
            _invoke(listener, instance, kw.get("using"), snapshot=False)

        post_save.connect(on_restore, sender=model, weak=False, dispatch_uid=uid)
        return

    if event == "updated":

        def on_update(sender: Any, instance: Any, created: bool = False, **kw: Any) -> None:
            if created or kw.get("raw") or is_soft_delete(instance, kw.get("update_fields")):
                return
            _invoke(listener, instance, kw.get("using"), snapshot=False)

        post_save.connect(on_update, sender=model, weak=False, dispatch_uid=uid)
        return

    def on_soft_delete(sender: Any, instance: Any, created: bool = False, **kw: Any) -> None:
        if created or kw.get("raw") or not is_soft_delete(instance, kw.get("update_fields")):
            return
        _invoke(listener, instance, kw.get("using"), snapshot=False)

    def on_hard_delete(sender: Any, instance: Any, **kw: Any) -> None:
        if _is_soft_deleted(instance):
            return  # a purge of a row already reported deleted
        _invoke(listener, instance, kw.get("using"), snapshot=True)

    post_save.connect(on_soft_delete, sender=model, weak=False, dispatch_uid=f"{uid}:soft")
    post_delete.connect(on_hard_delete, sender=model, weak=False, dispatch_uid=f"{uid}:hard")


# lifecycle transitions (karni.lifecycle)


def _states(value: Any) -> frozenset[str] | None:
    if value is None:
        return None
    items = [value] if isinstance(value, str) else list(value)
    return frozenset(str(getattr(item, "value", item)) for item in items)


def on_transition(
    model: ModelRef,
    field: str | None = None,
    *,
    to: Any = None,
    source: Any = None,
    queued: bool = False,
) -> Callable[[F], F]:
    """Run the decorated ``listener(instance)`` after a ``StateField`` transition of ``model``.

    ``@on_transition(Booking, "status", to="cancelled")`` hears every move
    into ``cancelled``; ``source=`` narrows to moves out of the given
    state(s); ``field`` defaults to every StateField of the model. The
    listener runs inside the save's transaction (it may raise to undo the
    transition), or in a Celery worker after commit with ``queued=True``.
    For the states themselves, receive :data:`karni.lifecycle.state_changed`
    (``source``, ``target`` and ``field`` arrive as keyword arguments).
    """
    if not isinstance(model, str) and not (
        isinstance(model, type) and issubclass(model, models.Model)
    ):
        raise KarniTypeError(
            "karni.events.on_transition() takes a model class or an 'app_label.ModelName' "
            f"string, got {model!r}.",
            code="E402",
        )
    targets, sources = _states(to), _states(source)

    def decorate(listener: F) -> F:
        from karni.lifecycle import state_changed

        prepared = _prepare(listener, queued)
        label = _model_label(model)

        def on_change(sender: Any, instance: Any, **kw: Any) -> None:
            if sender._meta.label != label and sender._meta.label_lower != label.lower():
                return
            if field is not None and kw.get("field") != field:
                return
            if targets is not None and kw.get("target") not in targets:
                return
            if sources is not None and kw.get("source") not in sources:
                return
            _invoke(prepared, instance, kw.get("using"), snapshot=False)

        uid = (
            f"karni.events:transition:{label}:{field}:{sorted(targets or ())}:"
            f"{sorted(sources or ())}:{_listener_id(prepared)}"
        )
        state_changed.connect(on_change, weak=False, dispatch_uid=uid)
        return listener

    return decorate
