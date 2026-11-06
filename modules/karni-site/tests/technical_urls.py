"""A urlconf with a page, Karni's probes and welcome page, and a project's own status route."""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.urls import include, path
from karni.health import probe_urls


def view(request: HttpRequest) -> HttpResponse:
    return HttpResponse("ok")


urlpatterns = [
    path("", view, name="home"),
    path("pricing/", view, name="pricing"),
    path("status/", view, name="status"),
    path("welcome-page/", view, name="karni-welcome"),
    path("", include(probe_urls)),
]
