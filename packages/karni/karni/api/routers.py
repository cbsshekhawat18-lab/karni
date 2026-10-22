"""Auto-registering DRF router: viewsets appear on the API by declaration alone.

:meth:`KarniRouter.autodiscover` walks every installed app, imports its
``viewsets`` (and ``api.viewsets``) module when present, and registers each
:class:`~karni.api.viewsets.BaseViewSet` subclass declared there — no
``router.register(...)`` boilerplate in projects.

Conventions:

* prefix — the viewset's ``route`` attribute, else the kebab-cased plural of
  the model name (:func:`pluralize` / :func:`kebab`), e.g. ``EventCategory``
  → ``event-categories``;
* basename — ``f"{app_label}-{kebab(ModelName)}"``, unique across apps;
* explicit wins — a viewset class already registered, or a prefix/basename
  already taken, is never overwritten (explicit-wins skips log at DEBUG;
  an auto-vs-auto collision logs a WARNING naming both viewsets);
* idempotent — calling ``autodiscover()`` twice on the same router is a no-op.

Override / escape hatch: set ``KARNI_API_ROUTER`` to the dotted path of your
own **zero-argument factory** that builds a router, pre-registers any explicit
routes (those then win over autodiscovery), calls ``autodiscover()`` and
returns it. The setting is consumed at first URLconf import (see
:mod:`karni.api.urls`); overriding it afterwards is a no-op. Per-viewset
knobs: ``auto_register = False`` opts a viewset out, ``route = "..."``
replaces the derived prefix.

The same router is Karni's model → viewset map: :func:`viewset_for_model`
answers "which viewset serves this model?" for relation scoping (a relation
field validates PKs against its target's routed viewset) and the schema's
``x-karni-relation`` extension.
"""

from __future__ import annotations

import logging
import re
import weakref
from collections.abc import Iterator
from importlib import import_module
from types import ModuleType
from typing import Any

from django.apps import AppConfig, apps
from django.conf import settings
from django.test.signals import setting_changed
from django.utils.module_loading import import_string, module_has_submodule
from rest_framework.routers import DefaultRouter

__all__ = [
    "KarniRouter",
    "get_default_router",
    "kebab",
    "pluralize",
    "resolve_router",
    "serves_model",
    "viewset_for_model",
]

logger = logging.getLogger(__name__)

_VOWELS = frozenset("aeiou")
_ES_ENDINGS = ("s", "x", "z", "ch", "sh")


def kebab(name: str) -> str:
    """Convert ``CamelCase`` to ``kebab-case`` (``APIKey`` → ``api-key``)."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "-", name).lower()


def pluralize(word: str) -> str:
    """Naive English plural used for route prefixes.

    Rules (deliberately simple; set ``route`` on the viewset for anything
    irregular): trailing ``y`` after a consonant → ``ies``; trailing ``s``,
    ``x``, ``z``, ``ch`` or ``sh`` → append ``es``; otherwise append ``s``.
    """
    if word.endswith("y") and len(word) > 1 and word[-2].lower() not in _VOWELS:
        return word[:-1] + "ies"
    if word.endswith(_ES_ENDINGS):
        return word + "es"
    return word + "s"


def default_route(model: type[Any]) -> str:
    """The conventional prefix for ``model``: kebab-cased plural of its name."""
    return pluralize(kebab(model.__name__))


class KarniRouter(DefaultRouter):
    """``DefaultRouter`` with idempotent, conflict-aware autodiscovery.

    Use it exactly like a ``DefaultRouter`` — explicit ``register()`` calls
    work as usual and take precedence — then call :meth:`autodiscover` to pick
    up every declared :class:`~karni.api.viewsets.BaseViewSet` in installed
    apps. See the module docstring for the conventions and escape hatches.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._discovered: set[type[Any]] = set()
        self._auto_prefixes: dict[str, type[Any]] = {}

    def autodiscover(self) -> None:
        """Register every eligible viewset declared by installed apps.

        Eligible: a ``BaseViewSet`` subclass defined in the app's ``viewsets``
        or ``api.viewsets`` module, with ``model`` set and ``auto_register``
        true. Idempotent per router instance — a second call is a no-op.
        """
        from karni.api.viewsets import BaseViewSet

        for app_config in apps.get_app_configs():
            for module in _viewset_modules(app_config):
                for viewset in _declared_viewsets(module, BaseViewSet):
                    self._register_discovered(viewset)

    def _register_discovered(self, viewset: type[Any]) -> None:
        if viewset in self._discovered:
            return
        self._discovered.add(viewset)
        model = viewset.model
        if viewset in {registered for _, registered, _ in self.registry}:
            logger.debug(
                "karni.api autodiscover: %s is already registered explicitly, so it is skipped.",
                _describe(viewset),
            )
            return
        prefix = getattr(viewset, "route", None) or default_route(model)
        holder = next((vs for p, vs, _ in self.registry if p == prefix), None)
        if holder is not None:
            if prefix in self._auto_prefixes:
                logger.warning(
                    "karni.api autodiscover: prefix %r is claimed by both %s and %s. "
                    "Karni keeps the first. Set route/auto_register on one of them.",
                    prefix,
                    _describe(self._auto_prefixes[prefix]),
                    _describe(viewset),
                )
            else:
                logger.debug(
                    "karni.api autodiscover: prefix %r already registered explicitly "
                    "(%s), so %s is skipped.",
                    prefix,
                    _describe(holder),
                    _describe(viewset),
                )
            return
        basename = f"{model._meta.app_label}-{kebab(model.__name__)}"
        holder = next((vs for _, vs, b in self.registry if b == basename), None)
        if holder is not None:
            logger.warning(
                "karni.api autodiscover: basename %r is claimed by both %s and %s. "
                "Karni keeps the first. Register the second explicitly with its own basename.",
                basename,
                _describe(holder),
                _describe(viewset),
            )
            return
        self.register(prefix, viewset, basename=basename)
        self._auto_prefixes[prefix] = viewset


_default_router: KarniRouter | None = None


def get_default_router() -> KarniRouter:
    """The default ``KARNI_API_ROUTER`` factory: cached router + autodiscover.

    Builds one module-level :class:`KarniRouter`, runs :meth:`~KarniRouter.
    autodiscover` (idempotent, so repeated calls are cheap) and returns it.
    Every caller — :mod:`karni.api.urls`, the schema generator — shares the
    same instance, so route lookups agree everywhere.

    Override / escape hatch: point ``KARNI_API_ROUTER`` at your own zero-arg
    factory to pre-register explicit routes before autodiscovery::

        # myproject/api.py
        def get_router():
            router = KarniRouter()
            router.register("events", MyEventViewSet, basename="events")
            router.autodiscover()  # explicit registration above wins
            return router
    """
    global _default_router
    if _default_router is None:
        _default_router = KarniRouter()
    _default_router.autodiscover()
    return _default_router


DEFAULT_ROUTER_FACTORY = "karni.api.routers.get_default_router"
"""Factory used when the ``KARNI_API_ROUTER`` setting is absent."""

_RESOLVED_ROUTERS: dict[str, Any] = {}
_MODEL_INDEX: weakref.WeakKeyDictionary[Any, tuple[int, dict[type[Any], type[Any]]]] = (
    weakref.WeakKeyDictionary()
)


def resolve_router() -> Any | None:
    """The router built by the ``KARNI_API_ROUTER`` factory, or ``None``.

    Resolved once per setting value and cached (the cache is dropped when
    ``override_settings`` changes ``KARNI_API_ROUTER``), so request-time
    callers such as relation scoping never re-run autodiscovery. ``None``
    when the factory cannot be imported.

    Override / escape hatch: point ``KARNI_API_ROUTER`` at your own
    zero-argument factory (see the module docstring).
    """
    dotted = getattr(settings, "KARNI_API_ROUTER", DEFAULT_ROUTER_FACTORY)
    if dotted not in _RESOLVED_ROUTERS:
        try:
            factory = import_string(dotted)
        except ImportError:
            return None
        _RESOLVED_ROUTERS[dotted] = factory()
    return _RESOLVED_ROUTERS[dotted]


def _served_model(viewset: type[Any]) -> type[Any] | None:
    served = getattr(viewset, "model", None)
    if served is None:
        served = getattr(getattr(viewset, "queryset", None), "model", None)
    return served


def serves_model(viewset: type[Any], model: type[Any]) -> bool:
    """True when ``viewset`` serves exactly ``model`` (its ``model``, else ``queryset.model``)."""
    return _served_model(viewset) is model


def viewset_for_model(model: type[Any], router: Any | None = None) -> type[Any] | None:
    """The first viewset registered on ``router`` that serves ``model``.

    ``router`` defaults to :func:`resolve_router`. "First" is registry order,
    so an explicitly registered viewset (registered before
    ``autodiscover()``) wins. ``None`` when no registered viewset serves the
    model — viewsets with ``auto_register = False`` count only once they are
    registered explicitly. The per-router index is rebuilt whenever the
    registry grows.
    """
    if router is None:
        router = resolve_router()
    registry = getattr(router, "registry", None)
    if registry is None:
        return None
    cached = _MODEL_INDEX.get(router)
    if cached is None or cached[0] != len(registry):
        index: dict[type[Any], type[Any]] = {}
        for _prefix, viewset, _basename in registry:
            served = _served_model(viewset)
            if served is not None:
                index.setdefault(served, viewset)
        cached = (len(registry), index)
        _MODEL_INDEX[router] = cached
    return cached[1].get(model)


def _reset_router_cache(sender: object, setting: str, **kwargs: Any) -> None:
    """Forget resolved routers when ``KARNI_API_ROUTER`` changes (tests)."""
    if setting == "KARNI_API_ROUTER":
        _RESOLVED_ROUTERS.clear()


setting_changed.connect(_reset_router_cache, dispatch_uid="karni.api.routers.router_cache")


def _viewset_modules(app_config: AppConfig) -> Iterator[ModuleType]:
    """Yield the app's ``viewsets`` and ``api.viewsets`` modules when present.

    ``module_has_submodule`` distinguishes "module absent" from "module raises
    ImportError", so real import errors in project code propagate loudly
    instead of being swallowed.
    """
    package = app_config.module
    if package is None:
        return
    if module_has_submodule(package, "viewsets"):
        yield import_module(f"{app_config.name}.viewsets")
    if module_has_submodule(package, "api"):
        api_package = import_module(f"{app_config.name}.api")
        if module_has_submodule(api_package, "viewsets"):
            yield import_module(f"{app_config.name}.api.viewsets")


def _declared_viewsets(module: ModuleType, base: type[Any]) -> Iterator[type[Any]]:
    """Viewset classes *defined in* ``module`` that opted into registration."""
    for obj in vars(module).values():
        if not isinstance(obj, type) or not issubclass(obj, base):
            continue
        if obj.__module__ != module.__name__:
            continue
        if getattr(obj, "model", None) is None:
            continue
        if not getattr(obj, "auto_register", True):
            continue
        yield obj


def _describe(viewset: type[Any]) -> str:
    return f"{viewset.__module__}.{viewset.__qualname__}"
