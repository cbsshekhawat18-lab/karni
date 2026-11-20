"""URLconf for the rules suite: its viewsets under ``api/``."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from tests.rulesapp import viewsets

router = DefaultRouter()
router.register("shops", viewsets.ShopViewSet, basename="shop")
router.register("items", viewsets.ItemViewSet, basename="item")
router.register("purchases", viewsets.PurchaseViewSet, basename="purchase")
router.register("lessons", viewsets.LessonViewSet, basename="lesson")

urlpatterns = [path("api/", include(router.urls))]
