"""The welcome view: 404 unless ``DEBUG`` is on, else the page built from live introspection."""

from __future__ import annotations

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse
from django.views import View

from karni.welcome.inventory import collect
from karni.welcome.page import render_page
from karni.welcome.status import run_checks

__all__ = ["WelcomeView"]


class WelcomeView(View):
    """``GET /`` on first boot. Never cached, never served with ``DEBUG`` off."""

    http_method_names = ["get", "head"]

    def get(self, request: HttpRequest) -> HttpResponse:
        if not settings.DEBUG:
            raise Http404
        response = HttpResponse(
            render_page(collect(), run_checks()), content_type="text/html; charset=utf-8"
        )
        response["Cache-Control"] = "no-store"
        response["X-Robots-Tag"] = "noindex"
        return response
