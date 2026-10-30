"""URLconf exposing the auto-discovered API router.

Projects mount it with one line::

    path("api/", include("karni.api.urls")),

At URLconf import time (Django imports the root URLconf lazily, after apps are
loaded) the factory named by the ``KARNI_API_ROUTER`` setting — default
:func:`karni.api.routers.get_default_router` — is called once; it owns
autodiscovery and returns the router whose URLs are exposed here.

It also mounts ``search/``, cross-model search
(:class:`karni.api.global_search.GlobalSearchView`, experimental), before the
routes, so it answers ``GET /api/search/`` whatever the router registers.

Override / escape hatch: point ``KARNI_API_ROUTER`` at your own zero-argument
factory to pre-register explicit routes before autodiscovery (see
:mod:`karni.api.routers`). The setting is consumed at first URLconf import;
changing it afterwards (e.g. with ``override_settings``) is a no-op — router
tests should build fresh ``KarniRouter`` instances instead. Declare your own
``path("api/search/", ...)`` before the include to replace the search endpoint.
"""

from __future__ import annotations

from django.conf import settings
from django.urls import path

from karni.api.global_search import GlobalSearchView
from karni.api.routers import KarniRouter
from karni.imports import import_setting

__all__ = ["router", "urlpatterns"]

DEFAULT_ROUTER_FACTORY = "karni.api.routers.get_default_router"
"""Factory used when the ``KARNI_API_ROUTER`` setting is absent."""

router: KarniRouter = import_setting(
    "KARNI_API_ROUTER", getattr(settings, "KARNI_API_ROUTER", DEFAULT_ROUTER_FACTORY)
)()

urlpatterns = [
    path("search/", GlobalSearchView.as_view(), name="karni-global-search"),
    *router.urls,
]
