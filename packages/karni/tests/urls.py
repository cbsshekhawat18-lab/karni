"""URLconf for karni's own test suite.

Mounts the three URL surfaces the accounts, api and admin suites exercise,
exactly the way a generated project does: the admin site (resolved from
``KARNI_ADMIN_SITE`` so site-swap tests stay honest), the accounts endpoints
under ``api/auth/`` and the auto-routed API under ``api/``. ``model-layer/``
holds two plain (non-DRF) views for the audit-population tests; they never
reach the OpenAPI schema.
"""

from __future__ import annotations

from django.conf import settings
from django.urls import include, path
from django.utils.module_loading import import_string

from tests import model_layer_views

_admin_site = import_string(settings.KARNI_ADMIN_SITE)

urlpatterns = [
    path("admin/", _admin_site.urls),
    path("api/auth/", include("karni.accounts.urls")),
    path("api/", include("karni.api.urls")),
    path(
        "model-layer/venues/sync/",
        model_layer_views.create_venue,
        name="model-layer-venue-sync",
    ),
    path(
        "model-layer/venues/async/",
        model_layer_views.acreate_venue,
        name="model-layer-venue-async",
    ),
]
