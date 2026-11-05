"""URLconf for the karni-storage test suite: exactly a project's wiring."""

from __future__ import annotations

from django.urls import include, path

urlpatterns = [
    path("api/", include("karni.api.urls")),
    path("api/", include("karni_storage.urls")),
]
