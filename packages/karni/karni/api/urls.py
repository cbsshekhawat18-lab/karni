"""URLconf exposing the auto-discovered API router.

Projects mount it with one line::

    path("api/", include("karni.api.urls")),

At URLconf import time (Django imports the root URLconf lazily, after apps are
loaded) the factory named by the ``KARNI_API_ROUTER`` setting — default
:func:`karni.api.routers.get_default_router` — is called once; it owns
autodiscovery and returns the router whose URLs are exposed here.

Override / escape hatch: point ``KARNI_API_ROUTER`` at your own zero-argument
factory to pre-register explicit routes before autodiscovery (see
:mod:`karni.api.routers`). The setting is consumed at first URLconf import;
changing it afterwards (e.g. with ``override_settings``) is a no-op — router
tests should build fresh ``KarniRouter`` instances instead.
"""

from __future__ import annotations

from django.conf import settings
from django.utils.module_loading import import_string

from karni.api.routers import KarniRouter

__all__ = ["router", "urlpatterns"]

DEFAULT_ROUTER_FACTORY = "karni.api.routers.get_default_router"
"""Factory used when the ``KARNI_API_ROUTER`` setting is absent."""

router: KarniRouter = import_string(getattr(settings, "KARNI_API_ROUTER", DEFAULT_ROUTER_FACTORY))()

urlpatterns = router.urls
