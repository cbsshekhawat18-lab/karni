"""The test URLconf plus demo mode's routes: the info route and, last, the React app."""

from __future__ import annotations

from django.urls import include, path

from karni.demo.urls import app_urls
from tests.urls import urlpatterns as base

urlpatterns = [
    *base,
    path("api/demo/", include("karni.demo.urls")),
    *app_urls(),
]
