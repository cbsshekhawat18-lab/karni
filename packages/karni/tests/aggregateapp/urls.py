"""URLconf for the aggregations suite: its viewsets under ``api/``."""

from __future__ import annotations

from django.urls import include, path

from karni.api.routers import KarniRouter
from tests.aggregateapp import viewsets

ROUTES = {
    "products": viewsets.ProductViewSet,
    "narrow-products": viewsets.NarrowProductViewSet,
    "categories": viewsets.CategoryViewSet,
}

router = KarniRouter()
for prefix, viewset in ROUTES.items():
    router.register(prefix, viewset, basename=f"aggregate-{prefix}")


def get_router() -> KarniRouter:
    return router


urlpatterns = [path("api/", include(router.urls))]
