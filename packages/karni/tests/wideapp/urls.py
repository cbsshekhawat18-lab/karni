"""URLconf of the wide-model suite: its viewsets under ``api/``, plus the admin."""

from __future__ import annotations

from django.conf import settings
from django.urls import include, path
from django.utils.module_loading import import_string

from karni.api.routers import KarniRouter
from tests.wideapp import viewsets

router = KarniRouter()
router.register("products", viewsets.ProductViewSet, basename="wide-products")
router.register("brands", viewsets.BrandViewSet, basename="wide-brands")


def get_router() -> KarniRouter:
    """``KARNI_API_ROUTER`` for the suite: route prefixes resolve against this router."""
    return router


urlpatterns = [
    path("admin/", import_string(settings.KARNI_ADMIN_SITE).urls),
    path("api/", include(router.urls)),
]
