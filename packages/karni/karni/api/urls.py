"""URLconf exposing the auto-discovered API router.

Projects mount it with one line::

    path("api/", include("karni.api.urls")),

At URLconf import time (Django imports the root URLconf lazily, after apps are
loaded) the factory named by the ``KARNI_API_ROUTER`` setting — default
:func:`karni.api.routers.get_default_router` — is called once; it owns
autodiscovery and returns the router whose URLs are exposed here.

While ``KARNI_NAVIGATION`` is set (experimental), ``navigation/`` comes first:
the requesting user's menu (:mod:`karni.navigation.api`).
It also mounts ``search/``, cross-model search
(:class:`karni.api.global_search.GlobalSearchView`, experimental), before the
routes, so it answers ``GET /api/search/`` whatever the router registers, and
``timeline/`` (:class:`karni.timeline.api.TimelineView`, experimental) while
``karni.timeline`` is installed and ``KARNI_TIMELINE_API`` is on.

Override / escape hatch: point ``KARNI_API_ROUTER`` at your own zero-argument
factory to pre-register explicit routes before autodiscovery (see
:mod:`karni.api.routers`). The setting is consumed at first URLconf import;
changing it afterwards (e.g. with ``override_settings``) is a no-op — router
tests should build fresh ``KarniRouter`` instances instead. Declare your own
``path("api/search/", ...)`` before the include to replace the search endpoint.
"""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.conf import settings
from django.urls import path

from karni.api.global_search import GlobalSearchView
from karni.api.routers import KarniRouter
from karni.imports import import_setting
from karni.navigation.api import build_urlpatterns as navigation_urlpatterns

__all__ = ["extra_urlpatterns", "router", "urlpatterns"]

DEFAULT_ROUTER_FACTORY = "karni.api.routers.get_default_router"
"""Factory used when the ``KARNI_API_ROUTER`` setting is absent."""

router: KarniRouter = import_setting(
    "KARNI_API_ROUTER", getattr(settings, "KARNI_API_ROUTER", DEFAULT_ROUTER_FACTORY)
)()


def _timeline_urlpatterns() -> list[Any]:
    """``timeline/`` while ``karni.timeline`` is installed and ``KARNI_TIMELINE_API`` is on."""
    if not apps.is_installed("karni.timeline"):
        return []
    from karni.timeline.api import build_urlpatterns

    return build_urlpatterns()


def _preferences_urlpatterns() -> list[Any]:
    """``preferences/`` while ``karni.preferences`` is installed and its API is on."""
    if not apps.is_installed("karni.preferences"):
        return []
    from karni.preferences.api import build_urlpatterns

    return build_urlpatterns()


#: What Karni mounts before the router's routes: ``navigation/`` while ``KARNI_NAVIGATION``
#: is set, ``search/``, ``timeline/`` with ``karni.timeline`` and ``preferences/`` with
#: ``karni.preferences``.
#: :func:`karni.api.versions.api_urls` mounts them in each version.
extra_urlpatterns = [
    *navigation_urlpatterns(),
    path("search/", GlobalSearchView.as_view(), name="karni-global-search"),
    *_timeline_urlpatterns(),
    *_preferences_urlpatterns(),
]

urlpatterns = [*extra_urlpatterns, *router.urls]
