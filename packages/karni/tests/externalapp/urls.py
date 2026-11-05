"""URLconf for the external tables suite: its viewsets under ``api/``, plus the admin."""

from __future__ import annotations

from django.conf import settings
from django.urls import include, path
from django.utils.module_loading import import_string

from karni.api.routers import KarniRouter
from tests.externalapp import viewsets

ROUTES = {
    "regions": viewsets.RegionViewSet,
    "sales": viewsets.SaleViewSet,
    "granted-sales": viewsets.GrantedSaleViewSet,
    "leaky-sales": viewsets.LeakySaleViewSet,
    "targets": viewsets.TargetViewSet,
    "region-totals": viewsets.RegionTotalViewSet,
    "stock": viewsets.StockViewSet,
    "mappings": viewsets.ProductMappingViewSet,
}

router = KarniRouter()
for prefix, viewset in ROUTES.items():
    router.register(prefix, viewset, basename=f"external-{prefix}")


def get_router() -> KarniRouter:
    return router


urlpatterns = [
    path("admin/", import_string(settings.KARNI_ADMIN_SITE).urls),
    path("api/", include(router.urls)),
]
