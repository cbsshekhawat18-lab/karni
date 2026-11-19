"""A small site for manage.py karni_site_seed: two pages with blocks, a seeded menu, the
site's defaults, and a page that fails while ``FAIL`` is true."""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import include, path

#: Whether /broken/ fails, as a page with a bug does.
FAIL = False


def page(template: str) -> Callable[[HttpRequest], HttpResponse]:
    def view(request: HttpRequest) -> HttpResponse:
        return render(request, template)

    return view


def broken(request: HttpRequest) -> HttpResponse:
    if FAIL:
        raise RuntimeError("the view has a bug")
    return render(request, "seed/about.html")


site = (
    [
        path("", page("seed/home.html"), name="home"),
        path("about/", page("seed/about.html"), name="about"),
        path("broken/", broken, name="broken"),
    ],
    "seeded",
)

urlpatterns = [
    path("", include("karni_site.urls")),
    path("", include(site)),
]

handler500 = "karni_site.views.server_error"
