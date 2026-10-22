"""URLconf for the lifecycle suite: its viewsets under ``api/``, plus the admin."""

from __future__ import annotations

from django.conf import settings
from django.urls import include, path
from django.utils.module_loading import import_string
from rest_framework.routers import DefaultRouter

from tests.lifecycleapp import viewsets

router = DefaultRouter()
router.register("orders", viewsets.OrderViewSet, basename="order")
router.register("stock", viewsets.StockViewSet, basename="stock")
router.register("slots", viewsets.SlotViewSet, basename="slot")
if viewsets.HAS_RANGES:
    router.register("reservations", viewsets.ReservationViewSet, basename="reservation")

urlpatterns = [
    path("admin/", import_string(settings.KARNI_ADMIN_SITE).urls),
    path("api/", include(router.urls)),
]
