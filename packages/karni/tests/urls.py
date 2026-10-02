"""URLconf for karni's own test suite.

Mounts the three URL surfaces the accounts, api and admin suites exercise,
exactly the way a generated project does: the admin site (resolved from
``KARNI_ADMIN_SITE`` so site-swap tests stay honest), the accounts endpoints
under ``api/auth/`` and the auto-routed API under ``api/``.
"""

from __future__ import annotations

from django.conf import settings
from django.urls import include, path
from django.utils.module_loading import import_string

_admin_site = import_string(settings.KARNI_ADMIN_SITE)

urlpatterns = [
    path("admin/", _admin_site.urls),
    path("api/auth/", include("karni.accounts.urls")),
    path("api/", include("karni.api.urls")),
]
