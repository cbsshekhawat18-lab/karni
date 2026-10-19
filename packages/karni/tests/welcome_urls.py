"""The scaffold's URLconf shape for the welcome tests: Karni's surfaces, the welcome route last."""

from __future__ import annotations

from django.urls import include, path

from karni.welcome import welcome_urls
from tests.urls import urlpatterns as _base

urlpatterns = [*_base, path("health/", include("karni.health.urls")), *welcome_urls()]
