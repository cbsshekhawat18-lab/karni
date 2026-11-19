"""The notifications suite's URLconf: the core suite sets KARNI_NOTIFY_API = False.

So the test app's OpenAPI snapshot stays as it is. These tests use
``ROOT_URLCONF="tests.notify.urls"`` and ``KARNI_API_ROUTER="tests.notify.urls.get_router"``.
"""

from __future__ import annotations

from django.urls import include, path

from karni.api.routers import KarniRouter
from karni.notify.api import build_urlpatterns
from karni.notify.viewsets import EmailTemplateViewSet


def get_router() -> KarniRouter:
    """The email editor's resource."""
    router = KarniRouter()
    router.register("email-templates", EmailTemplateViewSet, basename="email-templates")
    return router


urlpatterns = [
    path("api/auth/", include("karni.accounts.urls")),
    path("api/", include(build_urlpatterns(force=True))),
    path("api/", include(get_router().urls)),
]
