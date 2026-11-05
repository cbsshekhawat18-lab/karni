"""The coexistence project's URLconf: the accounts endpoints, as a project mounts them."""

from __future__ import annotations

from django.urls import include, path

urlpatterns = [path("api/auth/", include("karni.accounts.urls"))]
