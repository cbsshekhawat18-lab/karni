"""A URLconf that forgets karni_storage.urls (STORE004)."""

from __future__ import annotations

from django.urls import include, path

urlpatterns = [path("api/", include("karni.api.urls"))]
