"""URLs for the security header tests: the pages Django serves that a policy could break."""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerSplitView,
    SpectacularSwaggerView,
)

from karni.scoping import admin_site
from karni.security import csp_exempt, csp_extend
from karni.welcome.views import WelcomeView


def plain(request: HttpRequest) -> HttpResponse:
    return HttpResponse("<p>plain</p>")


@csp_extend({"img-src": ["https://tiles.example.com"], "frame-src": "https://maps.example.com"})
def with_map(request: HttpRequest) -> HttpResponse:
    return HttpResponse("<p>map</p>")


@csp_exempt
def exempt(request: HttpRequest) -> HttpResponse:
    return HttpResponse("<p>exempt</p>")


def own_policy(request: HttpRequest) -> HttpResponse:
    response = HttpResponse("<p>own</p>")
    response["Content-Security-Policy"] = "default-src 'none'"
    return response


urlpatterns = [
    path("staff-area/", admin_site().urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/docs-split/", SpectacularSwaggerSplitView.as_view(url_name="schema")),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    path("api/", include("karni.api.urls")),
    path("plain/", plain),
    path("map/", with_map),
    path("exempt/", exempt),
    path("own/", own_policy),
    path("", WelcomeView.as_view()),
]
