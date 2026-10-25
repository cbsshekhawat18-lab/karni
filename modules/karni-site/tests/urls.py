"""A small site: three pages in the ``website`` namespace, a page that fails, error handlers."""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import include, path


def page(template: str) -> Callable[[HttpRequest], HttpResponse]:
    def view(request: HttpRequest) -> HttpResponse:
        return render(request, template)

    return view


def boom(request: HttpRequest) -> HttpResponse:
    raise RuntimeError("the view failed")


site = (
    [
        path("", page("website/home.html"), name="home"),
        path("about/", page("website/about.html"), name="about"),
        path("services/web/", page("website/home.html"), name="service_web"),
    ],
    "website",
)

urlpatterns = [
    path("api/", include("karni.api.urls")),
    path("boom/", boom),
    path("", include(site)),
]

handler404 = "karni_site.views.page_not_found"
handler500 = "karni_site.views.server_error"
