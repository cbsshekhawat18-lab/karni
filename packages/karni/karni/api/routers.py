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
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from importlib import import_module
from types import ModuleType
from typing import Any

from django.apps import AppConfig, apps
from django.utils.module_loading import module_has_submodule
from rest_framework.routers import DefaultRouter

__all__ = ["KarniRouter", "get_default_router", "kebab", "pluralize"]

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
                "karni.api autodiscover: %s is already registered explicitly; skipping.",
                _describe(viewset),
            )
            return
        prefix = getattr(viewset, "route", None) or default_route(model)
        holder = next((vs for p, vs, _ in self.registry if p == prefix), None)
        if holder is not None:
            if prefix in self._auto_prefixes:
                logger.warning(
                    "karni.api autodiscover: prefix %r is claimed by both %s and %s; "
                    "keeping the first. Set route/auto_register on one of them.",
                    prefix,
                    _describe(self._auto_prefixes[prefix]),
                    _describe(viewset),
                )
            else:
                logger.debug(
                    "karni.api autodiscover: prefix %r already registered explicitly "
                    "(%s); skipping %s.",
                    prefix,
                    _describe(holder),
                    _describe(viewset),
                )
            return
        basename = f"{model._meta.app_label}-{kebab(model.__name__)}"
        holder = next((vs for _, vs, b in self.registry if b == basename), None)
        if holder is not None:
            logger.warning(
                "karni.api autodiscover: basename %r is claimed by both %s and %s; "
                "keeping the first. Register the second explicitly with its own basename.",
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
