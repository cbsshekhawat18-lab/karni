"""The catalog's own router and URLconf: ``api/search/`` and its four resources.

Tests use them with ``override_settings(ROOT_URLCONF="tests.searchapp.urls",
KARNI_API_ROUTER="tests.searchapp.urls.get_router")``, so search finds the
catalog's viewsets the way a project's router serves them.
"""

from __future__ import annotations

from django.urls import include, path

from karni.api.global_search import GlobalSearchView
from karni.api.routers import KarniRouter
from tests.searchapp.viewsets import NoteViewSet, ProductViewSet, ReportViewSet, SupplierViewSet


def get_router() -> KarniRouter:
    """The catalog's router (registration order is the order search lists resources in)."""
    router = KarniRouter()
    router.register("products", ProductViewSet, basename="searchapp-product")
    router.register("suppliers", SupplierViewSet, basename="searchapp-supplier")
    router.register("notes", NoteViewSet, basename="searchapp-note")
    router.register("reports", ReportViewSet, basename="searchapp-report")
    return router


urlpatterns = [
    path("api/search/", GlobalSearchView.as_view(), name="searchapp-search"),
    path("api/", include(get_router().urls)),
]
