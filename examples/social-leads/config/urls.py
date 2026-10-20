"""URL configuration for Social Leads.

Routes: Django admin, the OpenAPI schema and Swagger UI (drf-spectacular),
Karni's auth endpoints (/api/auth/), the auto-routed API (/api/), Karni's
health endpoints (/health/ liveness, /health/ready/ readiness) and, last,
the welcome page at "/" while DEBUG is on. Add project routes to
``urlpatterns`` below; to replace a single Karni endpoint, declare your
``path(...)`` for it BEFORE the include — first match wins. Your own
``path("", ...)`` replaces the welcome page the same way.
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from karni.welcome import media_urls, welcome_urls

urlpatterns = [
    # KARNI_ADMIN_PATH (env, default "admin/"): move the admin off the guessable path.
    path(settings.KARNI_ADMIN_PATH, admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/auth/", include("karni.accounts.urls")),
    path("api/", include("karni.api.urls")),
    path("health/", include("karni.health.urls")),
    # Uploads under MEDIA_URL while DEBUG is on and storage is local (dev only).
    *media_urls(),
    # Only while DEBUG is on, and only until a route above answers "/".
    *welcome_urls(),
]
