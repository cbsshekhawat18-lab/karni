"""URL configuration for EventHub.

Routes: Django admin, the OpenAPI schema and Swagger UI (drf-spectacular),
Karni's auth endpoints (/api/auth/), the auto-routed API (/api/), and
Karni's health endpoints (/health/ liveness, /health/ready/ readiness).
Add project routes to ``urlpatterns`` below; to replace a single Karni
endpoint, declare your ``path(...)`` for it BEFORE the include — first
match wins.
"""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/auth/", include("karni.accounts.urls")),
    path("api/", include("karni.api.urls")),
    path("payments/", include("karni_payments.urls")),
    path("health/", include("karni.health.urls")),
]
