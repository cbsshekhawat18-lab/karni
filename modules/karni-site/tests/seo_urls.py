"""A small site for the SEO tests: pages with {% karni_seo %}, cards and detail pages of rows.

The ``website`` pages of tests/urls.py are mounted under ``web/`` so their rows' addresses
resolve. ``BARE`` is a page the tests fill with the markup they need at ``/bare/``.
"""

from __future__ import annotations

from collections.abc import Callable

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import include, path
from django.views.generic import RedirectView

from tests import urls as base
from tests.testapp.models import Project

#: The markup /bare/ answers with, or None for a 404.
BARE: str | None = None


def page(template: str) -> Callable[[HttpRequest], HttpResponse]:
    def view(request: HttpRequest) -> HttpResponse:
        return render(request, template)

    return view


def projects(request: HttpRequest) -> HttpResponse:
    return render(request, "seo/projects.html", {"projects": Project.objects.all()})


def project(request: HttpRequest, slug: str) -> HttpResponse:
    found = Project.objects.filter(slug=slug).first()
    if found is None:
        raise Http404("no such project")
    return render(request, "seo/project.html", {"project": found})


def bare(request: HttpRequest) -> HttpResponse:
    if BARE is None:
        raise Http404("no bare page")
    return HttpResponse(BARE)


seo = (
    [
        path("", page("seo/home.html"), name="home"),
        path("about/", page("seo/about.html"), name="about"),
        path("projects/", projects, name="projects"),
        path("projects/<slug:slug>/", project, name="project"),
        path("old-about/", RedirectView.as_view(pattern_name="seo:about"), name="old_about"),
        path("bare/", bare, name="bare"),
    ],
    "seo",
)

urlpatterns = [
    path("", include("karni_site.urls")),
    path("web/", include(base.site)),
    path("", include(seo)),
]
handler404 = "karni_site.views.page_not_found"
handler500 = "karni_site.views.server_error"
