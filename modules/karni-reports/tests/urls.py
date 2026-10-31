"""URLconf for the karni-reports test suite: exactly a project's wiring (no module include)."""

from django.conf import settings
from django.urls import include, path
from django.utils.module_loading import import_string

_admin_site = import_string(settings.KARNI_ADMIN_SITE)

urlpatterns = [
    path("admin/", _admin_site.urls),
    path("api/auth/", include("karni.accounts.urls")),
    path("api/", include("karni.api.urls")),
]
