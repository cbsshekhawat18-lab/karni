"""A site whose topic and season pages sit behind a capture, with a known set of addresses
and no model: each view declares them with @pages."""

from __future__ import annotations

from typing import Any

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import include, path
from django.views.generic import TemplateView

from karni_site.sitemaps import pages

TOPICS = {"tides": "Tides and what they bring in", "harbours": "Harbours along the coast"}


def home(request: HttpRequest) -> HttpResponse:
    return render(request, "topics/page.html", {"title": "Harbour notes"})


@pages(lambda: [{"slug": slug} for slug in TOPICS])
def topic(request: HttpRequest, slug: str) -> HttpResponse:
    if slug not in TOPICS:
        raise Http404("no such topic")
    return render(request, "topics/page.html", {"title": TOPICS[slug]})


@pages({"season": "winter"})
class Season(TemplateView):
    template_name = "topics/page.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        return {**super().get_context_data(**kwargs), "title": f"The {kwargs['season']} tides"}


site = (
    [
        path("", home, name="home"),
        path("topics/<slug:slug>/", topic, name="topic"),
        path("seasons/<slug:season>/", Season.as_view(), name="season"),
    ],
    "topics",
)

urlpatterns = [
    path("", include("karni_site.urls")),
    path("", include(site)),
]
