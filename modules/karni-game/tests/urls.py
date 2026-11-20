"""URLconf for the karni-game test suite: exactly a project's wiring."""

from __future__ import annotations

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/game/", include("karni_game.urls")),
    path("api/", include("karni.api.urls")),
    path("payments/", include("karni_payments.urls")),
]
