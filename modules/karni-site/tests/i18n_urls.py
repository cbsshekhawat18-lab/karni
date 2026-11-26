"""A small site in two languages under ``i18n_patterns``: English at ``/en/...``, French at
``/fr/...``. The pages are in the ``website`` namespace, so the services' own addresses
(``Service.get_absolute_url``) are in each language too. karni_site's URLs stay outside.

``two_languages`` (tests/i18n_helpers.py) switches a test to it.
"""

from __future__ import annotations

from collections.abc import Callable

from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import include, path, translate_url
from django.utils import translation

from tests.testapp.models import Service

#: Each page's title and description in each language. "Contact" is the same word in both.
TEXTS: dict[str, dict[str, tuple[str, str]]] = {
    "home": {
        "en": ("Tide tables", "When the sea comes in and goes out, day by day."),
        "fr": ("Horaires des marées", "Quand la mer monte et descend, jour après jour."),
    },
    "about": {
        "en": ("About us", "Who keeps the tide tables, and how."),
        "fr": ("À propos", "Qui tient les horaires des marées, et comment."),
    },
    "contact": {
        "en": ("Contact", "Write to the people who keep the tables."),
        "fr": ("Contact", "Écrire à celles et ceux qui tiennent les horaires."),
    },
}


def _context(request: HttpRequest, title: str, description: str) -> dict[str, object]:
    switch = [(code, translate_url(request.path, code)) for code, _name in settings.LANGUAGES]
    return {"title": title, "description": description, "switch": switch}


def page(name: str) -> Callable[[HttpRequest], HttpResponse]:
    def view(request: HttpRequest) -> HttpResponse:
        title, description = TEXTS[name][translation.get_language() or "en"]
        return render(request, "lang/base.html", _context(request, title, description))

    return view


def service(request: HttpRequest, slug: str) -> HttpResponse:
    found = get_object_or_404(Service.objects.filter(published=True), slug=slug)
    context = _context(request, found.title, f"{found.title}: what we do, in a few lines.")
    return render(request, "lang/base.html", {**context, "service": found})


site = (
    [
        path("", page("home"), name="home"),
        path("about/", page("about"), name="about"),
        path("contact/", page("contact"), name="contact"),
        path("services/<slug:slug>/", service, name="service"),
    ],
    "website",
)

urlpatterns = [
    path("", include("karni_site.urls")),
    *i18n_patterns(path("", include(site))),
]
