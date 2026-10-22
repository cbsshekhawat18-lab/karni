"""Named model scopes: the filters Karni's default managers apply.

A *scope* is a named, ordered filter. Karni's default managers (built on
:class:`karni.managers.ScopedManagerMixin`) apply every active scope that
covers their model to every queryset they build. Core registers one:

* ``soft_delete`` (order 10) hides soft-deleted rows of every model with a
  ``deleted_at`` column (:class:`karni.models.SoftDeleteModel`).

Modules add more through the ``karni.scopes`` entry-point group, so
installing the module is the whole change. The planned ``karni-tenancy``
module adds ``tenant`` (order 20) to every ``BaseModel`` this way::

    # the module's pyproject.toml
    [project.entry-points."karni.scopes"]
    tenant = "karni_tenancy.scopes:TenantScope"

Scopes reach everything built from a model's default manager:
``Model.objects``, related managers (``parent.children``, M2M),
``prefetch_related``, the admin, and DRF relation fields and lookups that go
through ``_default_manager``. They do not reach Django's base manager
(forward FK access ``child.parent``, ``refresh_from_db``, deletion
cascades), joins across relations (``filter(parent__name=...)``) or raw SQL.

Lifting one: ``Model.objects.without("soft_delete", reason="...")`` removes
exactly the named scopes and keeps every other one. The reason is required
and logged on the ``karni.scopes`` logger.

Override / escape hatches, least to most drastic: ``without()`` per query;
``ScopeMeta`` on a model, which each scope reads through :func:`scope_option`
(``class ScopeMeta: tenant = "shared"``); a scope subclass registered under a
new name; ``KARNI_SCOPES``, a list of scope names in pipeline order, to
disable or reorder scopes project-wide.
"""

from __future__ import annotations

import abc
import logging
import weakref
from collections.abc import Iterable
from importlib import metadata
from typing import TYPE_CHECKING, Any, ClassVar, Final

from django.conf import settings
from django.core.signals import setting_changed

from karni.errorcodes import KarniError
from karni.exceptions import KarniImproperlyConfigured

if TYPE_CHECKING:
    from django.db import models
    from django.db.models import QuerySet

__all__ = [
    "ENTRY_POINT_GROUP",
    "SETTING",
    "SOFT_DELETE",
    "Scope",
    "ScopeContextMissing",
    "ScopeError",
    "ScopeRegistry",
    "SoftDeleteScope",
    "UnknownScope",
    "apply_scopes",
    "registry",
    "scope_option",
]

logger = logging.getLogger(__name__)

#: Name of core's soft-delete scope.
SOFT_DELETE: Final[str] = "soft_delete"
#: Entry-point group modules register scopes under.
ENTRY_POINT_GROUP: Final[str] = "karni.scopes"
#: Project setting: a list of scope names, in pipeline order (``None`` = all).
SETTING: Final[str] = "KARNI_SCOPES"


class ScopeError(KarniError):
    """Misuse of the scope API: no scope named, an unknown name, no reason."""


class UnknownScope(ScopeError, LookupError):
    """A scope name that no built-in scope or installed module registers."""

    code = "E003"


class ScopeContextMissing(ScopeError):
    """A scope cannot filter because the context it needs is not bound.

    Scopes raise it to fail closed. A tenant scope raises it when no tenant
    is bound, and does not fall back to returning every row. ``fix`` says
    how to bind the context, for example ``"wrap the task body in
    tenant_context(t)"``.
    """

    code = "E006"

    def __init__(self, model: type[models.Model], scope: str, fix: str | None = None) -> None:
        self.model = model
        self.scope = scope
        how = fix or f"bind the current {scope} before querying"
        super().__init__(
            f"{model._meta.label} is filtered by the {scope!r} scope, but no {scope} is "
            f"bound, and Karni fails closed rather than return every {scope}'s rows. "
            f"Fix: {how}. To query across every {scope} on purpose, use "
            f'{model.__name__}.objects.without("{scope}", reason="...").'
        )


class Scope(abc.ABC):
    """One named filter in the default-manager pipeline.

    Subclass it, set ``name`` and ``order``, implement :meth:`applies_to` and
    :meth:`filter`, then register an instance through a ``karni.scopes``
    entry point or :meth:`ScopeRegistry.register`.
    """

    #: Unique identifier, used by ``without()``, ``KARNI_SCOPES`` and ``ScopeMeta``.
    name: ClassVar[str]
    #: Position in the pipeline, ascending: soft_delete is 10, tenant 20.
    order: ClassVar[int]
    #: Level at which ``without()`` logs that this scope was lifted.
    lift_log_level: ClassVar[int] = logging.INFO

    @abc.abstractmethod
    def applies_to(self, model: type[models.Model]) -> bool:
        """Whether this scope filters ``model``'s default-manager querysets.

        Called once per model, then cached. The cache resets when scopes are
        registered or ``KARNI_SCOPES`` changes. Read per-model opt-outs with
        :func:`scope_option`.
        """

    @abc.abstractmethod
    def filter(self, queryset: QuerySet[Any]) -> QuerySet[Any]:
        """Return ``queryset`` narrowed by this scope.

        This runs whenever a default manager *builds* a queryset. That
        includes import time, for a class-level ``queryset =
        Model.objects.all()``. A scope whose predicate depends on the current
        request or task (a tenant) must therefore read that context when the
        SQL is compiled, from an expression whose ``as_sql`` reads it, not
        here. It raises :class:`ScopeContextMissing` there when nothing is
        bound.
        """

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name!r} order={self.order}>"


class SoftDeleteScope(Scope):
    """``soft_delete`` hides rows whose ``deleted_at`` is set.

    It covers every model with a concrete ``deleted_at`` field. That means
    each :class:`karni.models.SoftDeleteModel`, plus the historical copies
    that data migrations use (``KarniUserManager`` is
    ``use_in_migrations``), exactly as the hard-coded filter it replaces
    did. Lifting it logs at DEBUG, because the admin lifts it on every
    changelist.
    """

    name = SOFT_DELETE
    order = 10
    lift_log_level = logging.DEBUG

    def applies_to(self, model: type[models.Model]) -> bool:
        return any(field.name == "deleted_at" for field in model._meta.concrete_fields)

    def filter(self, queryset: QuerySet[Any]) -> QuerySet[Any]:
        return queryset.filter(deleted_at__isnull=True)


def scope_option(model: type[models.Model], name: str, default: Any = None) -> Any:
    """``model.ScopeMeta.<name>``, inherited like any class attribute, else ``default``.

    This is the per-model switch each scope interprets for itself. Under the
    tenancy module, for example, ``class ScopeMeta: tenant = "shared"``
    marks a model as global.
    """
    return getattr(getattr(model, "ScopeMeta", None), name, default)


class ScopeRegistry:
    """The registered scopes, the active pipeline, and a per-model cache.

    The module-level :data:`registry` is the one Karni's managers use.
    Built-in scopes are always present. ``karni.scopes`` entry points load on
    first use, and each one names a :class:`Scope` subclass or instance.
    :meth:`register` adds a scope at runtime, from an ``AppConfig.ready()``
    or a test.
    """

    def __init__(
        self,
        builtin: Iterable[Scope] = (),
        *,
        entry_point_group: str | None = ENTRY_POINT_GROUP,
    ) -> None:
        self._builtin = tuple(builtin)
        self._group = entry_point_group
        self._scopes: dict[str, Scope] | None = None
        self._active: tuple[Scope, ...] | None = None
        self._per_model: weakref.WeakKeyDictionary[type, tuple[Scope, ...]] = (
            weakref.WeakKeyDictionary()
        )

    # -- registration --------------------------------------------------------

    def register(self, scope: Scope) -> Scope:
        """Add ``scope``. A duplicate name raises ``ImproperlyConfigured``."""
        self._add(self._loaded(), scope, source="register()")
        self.clear_cache()
        return scope

    def unregister(self, name: str) -> Scope:
        """Remove and return the scope called ``name``."""
        scopes = self._loaded()
        if name not in scopes:
            raise self._unknown(name)
        scope = scopes.pop(name)
        self.clear_cache()
        return scope

    def reset(self) -> None:
        """Drop runtime registrations, and re-read entry points on next use."""
        self._scopes = None
        self.clear_cache()

    def clear_cache(self) -> None:
        """Recompute the active pipeline and per-model scopes on next use."""
        self._active = None
        self._per_model = weakref.WeakKeyDictionary()

    # -- lookups -------------------------------------------------------------

    def get(self, name: str) -> Scope:
        """The registered scope called ``name``, active or not."""
        scopes = self._loaded()
        if name not in scopes:
            raise self._unknown(name)
        return scopes[name]

    def names(self) -> tuple[str, ...]:
        """Every registered scope name, in default pipeline order."""
        return tuple(scope.name for scope in _by_order(self._loaded().values()))

    def active(self) -> tuple[Scope, ...]:
        """The pipeline: every registered scope by ``order``, or ``KARNI_SCOPES``."""
        if self._active is None:
            self._active = self._resolve_active(self._loaded())
        return self._active

    def for_model(self, model: type[models.Model]) -> tuple[Scope, ...]:
        """The active scopes that filter ``model``, in pipeline order."""
        cached = self._per_model.get(model)
        if cached is None:
            cached = tuple(scope for scope in self.active() if scope.applies_to(model))
            self._per_model[model] = cached
        return cached

    def lift(
        self, model: type[models.Model], names: tuple[str, ...], reason: object
    ) -> frozenset[str]:
        """Validate and log a ``without(*names, reason=...)`` call on ``model``.

        It returns the names to skip. It raises :class:`ScopeError` when no
        name or no reason is given, and :class:`UnknownScope` for a name that
        nothing registers. A registered scope that does not cover ``model``,
        or that ``KARNI_SCOPES`` disabled, is a valid no-op, so code stays
        portable across installs.
        """
        model_name = model.__name__
        if not names:
            raise ScopeError(
                f"{model_name}.objects.without() needs the name of the scope to lift, "
                f'e.g. without("{SOFT_DELETE}", reason="..."). '
                f"Registered scopes: {', '.join(self.names())}.",
                code="E003",
            )
        scopes = self._loaded()
        for name in names:
            if name not in scopes:
                raise self._unknown(name)
        if not isinstance(reason, str) or not reason.strip():
            quoted = ", ".join(f'"{name}"' for name in names)
            raise ScopeError(
                f"{model_name}.objects.without({quoted}) needs a reason: pass "
                'reason="<why this query must see rows the scope hides>", e.g. '
                'reason="admin: deleted filter". The reason is logged.',
                code="E004",
            )
        level = max(scopes[name].lift_log_level for name in names)
        logger.log(
            level, "lifted scope(s) %s on %s: %s", ", ".join(names), model._meta.label, reason
        )
        return frozenset(names)

    # -- internals -----------------------------------------------------------

    def _loaded(self) -> dict[str, Scope]:
        if self._scopes is None:
            scopes: dict[str, Scope] = {}
            for scope in self._builtin:
                self._add(scopes, scope, source="built-in scope")
            for entry_point in self._entry_points():
                source = f"{self._group} entry point {entry_point.name!r} ({entry_point.value})"
                self._add(scopes, _load_entry_point(entry_point, source), source=source)
            self._scopes = scopes
        return self._scopes

    def _entry_points(self) -> list[metadata.EntryPoint]:
        if self._group is None:
            return []
        return sorted(metadata.entry_points(group=self._group), key=lambda ep: ep.name)

    @staticmethod
    def _add(scopes: dict[str, Scope], scope: object, *, source: str) -> None:
        if not isinstance(scope, Scope):
            raise KarniImproperlyConfigured(
                f"{source}: expected a karni.scopes.Scope subclass or instance, got {scope!r}.",
                code="E002",
            )
        kind = type(scope).__name__
        name = getattr(scope, "name", None)
        order = getattr(scope, "order", None)
        if not isinstance(name, str) or not name.isidentifier():
            raise KarniImproperlyConfigured(
                f"{source}: {kind}.name must be an identifier such as 'tenant', got {name!r}.",
                code="E002",
            )
        if isinstance(order, bool) or not isinstance(order, int):
            raise KarniImproperlyConfigured(
                f"{source}: {kind}.order must be an int (soft_delete is 10, tenant 20), "
                f"got {order!r}.",
                code="E002",
            )
        if name in scopes:
            raise KarniImproperlyConfigured(
                f"{source}: a scope named {name!r} is already registered ({scopes[name]!r}). "
                "Give the new scope another name, or unregister the existing one first.",
                code="E002",
            )
        scopes[name] = scope

    @staticmethod
    def _resolve_active(scopes: dict[str, Scope]) -> tuple[Scope, ...]:
        configured = getattr(settings, SETTING, None)
        if configured is None:
            return tuple(_by_order(scopes.values()))
        registered = ", ".join(scope.name for scope in _by_order(scopes.values()))
        if not isinstance(configured, list | tuple) or not all(
            isinstance(name, str) for name in configured
        ):
            raise KarniImproperlyConfigured(
                f"{SETTING} must be a list of scope names in pipeline order "
                f"(registered: {registered}), or unset for all of them. Got {configured!r}.",
                code="E002",
            )
        unknown = [name for name in configured if name not in scopes]
        if unknown:
            raise KarniImproperlyConfigured(
                f"{SETTING} names unknown scope(s) {', '.join(unknown)} (registered: "
                f"{registered}). Remove them, or install the module that provides them.",
                code="E002",
            )
        if len(set(configured)) != len(configured):
            raise KarniImproperlyConfigured(
                f"{SETTING} lists a scope twice: {configured!r}.", code="E002"
            )
        return tuple(scopes[name] for name in configured)

    def _unknown(self, name: str) -> UnknownScope:
        return UnknownScope(
            f"No scope named {name!r} is registered (registered: {', '.join(self.names())}). "
            "Check the spelling, or install the module that provides it."
        )


def _by_order(scopes: Iterable[Scope]) -> list[Scope]:
    return sorted(scopes, key=lambda scope: (scope.order, scope.name))


def _load_entry_point(entry_point: metadata.EntryPoint, source: str) -> object:
    try:
        loaded = entry_point.load()
    except Exception as exc:  # noqa: BLE001 - re-raised with the entry point named
        raise KarniImproperlyConfigured(f"{source} failed to load: {exc}", code="E002") from exc
    if isinstance(loaded, type) and issubclass(loaded, Scope):
        return loaded()
    return loaded


#: The registry Karni's default managers apply.
registry = ScopeRegistry([SoftDeleteScope()])


def apply_scopes(queryset: QuerySet[Any], *, lifted: frozenset[str] = frozenset()) -> QuerySet[Any]:
    """Apply every active scope covering ``queryset.model``, except ``lifted`` ones."""
    for scope in registry.for_model(queryset.model):
        if scope.name not in lifted:
            queryset = scope.filter(queryset)
    return queryset


def _reset_on_setting_change(*, setting: str, **kwargs: Any) -> None:
    if setting == SETTING:
        registry.clear_cache()


setting_changed.connect(_reset_on_setting_change)
