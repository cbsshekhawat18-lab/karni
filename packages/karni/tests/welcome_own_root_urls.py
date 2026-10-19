"""A project with its own root route: the welcome route, still mounted last, never answers."""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.urls import path

from karni.welcome import welcome_urls
from tests.urls import urlpatterns as _base


def home(request: HttpRequest) -> HttpResponse:
    return HttpResponse("my own home")


urlpatterns = [path("", home), *_base, *welcome_urls()]
