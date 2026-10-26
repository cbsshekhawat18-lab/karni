"""A small site: pages in the ``website`` namespace (two with forms), a page that fails,
karni_site's form view, the error handlers and the admin."""

from __future__ import annotations

from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import include, path
from django.utils.module_loading import import_string

from tests.testapp.models import Service

_admin_site = import_string(settings.KARNI_ADMIN_SITE)


def page(template: str) -> Callable[[HttpRequest], HttpResponse]:
    def view(request: HttpRequest) -> HttpResponse:
        return render(request, template)

    return view


def service(request: HttpRequest, slug: str) -> HttpResponse:
    found = get_object_or_404(Service.objects.filter(published=True), slug=slug)
    return render(request, "website/service.html", {"service": found})


def boom(request: HttpRequest) -> HttpResponse:
    raise RuntimeError("the view failed")


site = (
    [
        path("", page("website/home.html"), name="home"),
        path("about/", page("website/about.html"), name="about"),
        path("services/web/", page("website/home.html"), name="service_web"),
        path("services/<slug:slug>/", service, name="service"),
        path("contact/", page("website/contact.html"), name="contact"),
        path("book/", page("website/book.html"), name="book"),
        path("apply/", page("website/apply.html"), name="apply"),
    ],
    "website",
)

urlpatterns = [
    path("admin/", _admin_site.urls),
    path("api/", include("karni.api.urls")),
    path("boom/", boom),
    path("", include("karni_site.urls")),
    path("", include(site)),
]

handler404 = "karni_site.views.page_not_found"
handler500 = "karni_site.views.server_error"
