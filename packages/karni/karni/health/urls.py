"""URLconf for Karni's health endpoints.

Projects mount this wherever they like — the Karni convention is::

    path("health/", include("karni.health.urls"))

giving ``/health/`` (liveness) and ``/health/ready/`` (readiness).  To change
paths or swap views, route :mod:`karni.health.views` (or your own views)
directly in the project URLconf instead of including this module.
"""

from __future__ import annotations

from django.urls import URLPattern, path

from karni.health import views

app_name = "karni_health"

urlpatterns: list[URLPattern] = [
    path("", views.liveness, name="liveness"),
    path("ready/", views.readiness, name="readiness"),
]
