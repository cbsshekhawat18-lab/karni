"""URL configuration for {{ cookiecutter.project_name }}.

Routes: Django admin, the OpenAPI schema and Swagger UI (drf-spectacular),
Karni's auth endpoints (/api/auth/), the auto-routed API (/api/, or /api/v1/ once
KARNI_API_VERSION is set), Karni's health endpoints (/healthz and /readyz for probes,
/health/ and /health/ready/ as before) and, last,
the welcome page at "/" while DEBUG is on. Swagger UI is the split view: its
start-up script is a file, so the content security policy allows no inline
script on that page either. Add project routes to
``urlpatterns`` below. To replace a single Karni endpoint, declare your
``path(...)`` for it BEFORE the include, because the first match wins. Your own
``path("", ...)`` replaces the welcome page the same way. ``karni make site``
inserts its include at the ``# karni:urls`` marker, so keep that line.
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerSplitView
from karni.api.versions import api_urls
from karni.health.probe_urls import urlpatterns as probe_urls
from karni.welcome import media_urls, welcome_urls

urlpatterns = [
    # KARNI_ADMIN_PATH (env, default "admin/"): move the admin off the guessable path.
    path(settings.KARNI_ADMIN_PATH, admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerSplitView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path("api/auth/", include("karni.accounts.urls")),
    # /api/, or one mount per version when KARNI_API_VERSION is set (karni.api.versions).
    *api_urls(),
    path("health/", include("karni.health.urls")),
    # /healthz (liveness) and /readyz (database, cache and broker): what compose and a proxy ask.
    *probe_urls,
    # Uploads under MEDIA_URL while DEBUG is on and storage is local (dev only).
    *media_urls(),
    # Project routes that `karni make` wires (a public site's include goes here).
    # karni:urls
    # Only while DEBUG is on, and only until a route above answers "/".
    *welcome_urls(),
]
