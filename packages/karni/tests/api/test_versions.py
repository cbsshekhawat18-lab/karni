"""API versions (experimental): prefix, unversioned API, deprecation headers, a document each."""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType
from typing import Any

import pytest
from django.core import checks as django_checks
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.test import Client
from django.urls import include, path
from rest_framework.versioning import URLPathVersioning
from rest_framework.views import APIView

from karni.api import versions as api_versions
from karni.api.routers import KarniRouter
from karni.api.urls import router
from karni.api.versions import ApiVersion, api_urls, version_headers
from karni.checks import check_api_versions
from tests.testapp.models import Event
from tests.testapp.viewsets import VenueViewSet

pytestmark = pytest.mark.django_db

Setup = Callable[..., None]


def venues_only() -> KarniRouter:
    """A second version's router: it serves venues and nothing else."""
    own = KarniRouter()
    own.register("venues", VenueViewSet, basename="venue")
    return own


@pytest.fixture
def setup(settings: Any, monkeypatch: pytest.MonkeyPatch) -> Setup:
    """Mount ``api_urls()`` for the settings given, with DRF reading the version from the URL.

    ``karni_settings()`` puts ``URLPathVersioning`` in ``REST_FRAMEWORK`` before any view class
    exists. The suite's settings are fixed, so the class attributes DRF reads at import are set
    here.
    """

    def _setup(
        *, version: str = "v1", versions: dict[str, Any] | None = None, **extra: Any
    ) -> None:
        settings.KARNI_API_VERSION = version
        settings.KARNI_API_VERSIONS = versions or {}
        for name, value in extra.items():
            setattr(settings, name, value)
        monkeypatch.setattr(APIView, "versioning_class", URLPathVersioning)
        monkeypatch.setattr(URLPathVersioning, "default_version", version or None)
        module = ModuleType("versioned_urls")
        module.__dict__["urlpatterns"] = [
            path("api/auth/", include("karni.accounts.urls")),
            *api_urls(),
        ]
        settings.ROOT_URLCONF = module

    return _setup


def test_without_settings_the_api_is_mounted_as_before() -> None:
    patterns = api_urls()
    assert len(patterns) == 1
    assert str(patterns[0].pattern) == "api/"


def test_the_version_prefix_mounts_the_api_and_the_unversioned_api_is_kept(
    setup: Setup, client: Client
) -> None:
    setup()
    assert client.get("/api/v1/events/").status_code == 200
    assert client.get("/api/events/").status_code == 200
    assert client.get("/api/v2/events/").status_code == 404


def test_the_view_sees_the_version(setup: Setup) -> None:
    setup()
    from karni.api.routers import viewset_for_model

    assert viewset_for_model(Event) is not None
    from rest_framework.test import APIRequestFactory

    from tests.testapp.viewsets import EventViewSet

    view = EventViewSet.as_view({"get": "list"})
    request = APIRequestFactory().get("/api/v1/events/")
    response = view(request, version="v1")
    assert response.status_code == 200
    assert response.renderer_context["request"].version == "v1"


def test_redirect_sends_the_unversioned_api_to_the_current_version(
    setup: Setup, client: Client
) -> None:
    setup(KARNI_API_UNVERSIONED="redirect")
    response = client.get("/api/events/?page=2")
    assert response.status_code == 308
    assert response["Location"] == "/api/v1/events/?page=2"
    assert client.post("/api/events/", {}).status_code == 308
    assert client.get("/api/v1/events/").status_code == 200
    assert client.get("/api/v1/nothing/").status_code == 404  # not a redirect loop


def test_remove_drops_the_unversioned_api(setup: Setup, client: Client) -> None:
    setup(KARNI_API_UNVERSIONED="remove")
    assert client.get("/api/events/").status_code == 404
    assert client.get("/api/v1/events/").status_code == 200
    assert client.get("/api/auth/terms/").status_code in (200, 404)  # auth is not versioned


def test_a_version_can_serve_its_own_router(setup: Setup, client: Client) -> None:
    setup(
        version="v2",
        versions={"v1": {"router": f"{__name__}.venues_only"}, "v2": {}},
    )
    assert client.get("/api/v1/venues/").status_code == 200
    assert client.get("/api/v1/events/").status_code == 404
    assert client.get("/api/v2/events/").status_code == 200
    assert client.get("/api/events/").status_code == 200  # the unversioned API is the current one


# deprecation headers


def test_a_deprecated_version_sends_deprecation_sunset_and_link(
    setup: Setup, client: Client, settings: Any
) -> None:
    setup(
        version="v2",
        versions={
            "v1": {
                "deprecated": "2026-06-01",
                "sunset": "2027-01-31",
                "notes": "https://example.com/api-v1-to-v2",
            },
            "v2": {},
        },
    )
    settings.MIDDLEWARE = [*settings.MIDDLEWARE, "karni.api.versions.ApiVersionHeadersMiddleware"]
    old, new = client.get("/api/v1/events/"), client.get("/api/v2/events/")
    assert old.status_code == 200
    assert old["Deprecation"] == "@1780272000"
    assert old["Sunset"] == "Sun, 31 Jan 2027 00:00:00 GMT"
    assert old["Link"] == '<https://example.com/api-v1-to-v2>; rel="deprecation"; type="text/html"'
    for header in ("Deprecation", "Sunset", "Link"):
        assert header not in new
        assert header not in client.get("/api/events/")


def test_the_headers_reach_error_responses_too(setup: Setup, client: Client, settings: Any) -> None:
    setup(version="v2", versions={"v1": {"deprecated": True}, "v2": {}})
    settings.MIDDLEWARE = [*settings.MIDDLEWARE, "karni.api.versions.ApiVersionHeadersMiddleware"]
    response = client.post("/api/v1/events/", {})
    assert response.status_code in (401, 403)
    assert response["Deprecation"] == "true"
    assert "Sunset" not in response and "Link" not in response


def test_the_headers_function_for_each_kind_of_version() -> None:
    assert version_headers(ApiVersion("v1")) == {}
    assert version_headers(ApiVersion("v1", deprecated=True)) == {"Deprecation": "true"}


def test_the_middleware_is_left_out_while_nothing_is_deprecated(setup: Setup) -> None:
    from django.core.exceptions import MiddlewareNotUsed

    setup()
    with pytest.raises(MiddlewareNotUsed):
        api_versions.ApiVersionHeadersMiddleware(lambda request: HttpResponse())


def test_karni_settings_lists_the_middleware() -> None:
    from karni.conf.base import BASE

    assert "karni.api.versions.ApiVersionHeadersMiddleware" in BASE["MIDDLEWARE"]


# one OpenAPI document and Swagger UI per version


def test_each_version_has_its_own_openapi_document(setup: Setup, client: Client) -> None:
    setup(
        version="v2",
        versions={"v1": {"router": f"{__name__}.venues_only"}, "v2": {}},
    )
    v1 = client.get("/api/v1/schema/?format=json").json()
    v2 = client.get("/api/v2/schema/?format=json").json()
    served = {p for p in v1["paths"] if p.startswith("/api/v")}
    assert {"/api/v1/venues/", "/api/v1/venues/{id}/"} <= served
    assert all(p.startswith("/api/v1/venues/") for p in served)
    assert "/api/auth/login/" in v1["paths"]  # the auth routes are not versioned
    assert "/api/v2/events/" in v2["paths"]
    assert not any(p.startswith("/api/v1/") for p in v2["paths"])
    assert not any("/schema/" in p or "/docs/" in p for p in [*v1["paths"], *v2["paths"]])
    assert client.get("/api/v1/docs/").status_code == 200


def test_the_unversioned_document_is_the_current_versions(setup: Setup, client: Client) -> None:
    setup(version="v2", versions={"v1": {"router": f"{__name__}.venues_only"}, "v2": {}})
    from drf_spectacular.generators import SchemaGenerator

    paths = SchemaGenerator().get_schema(request=None, public=True)["paths"]
    assert "/api/v1/venues/" not in paths


# checks


def _ids(messages: list[django_checks.CheckMessage]) -> list[str]:
    return [m.id for m in messages]


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"KARNI_API_VERSION": "V 1"}, "karni.E590"),
        ({"KARNI_API_VERSIONS": ["v1"]}, "karni.E590"),
        ({"KARNI_API_VERSIONS": {"v1": {"sunsets": "2027-01-01"}}}, "karni.E590"),
        ({"KARNI_API_VERSIONS": {"v1": {"sunset": "soon"}}}, "karni.E590"),
        ({"KARNI_API_VERSIONS": {"v1": {"router": "no.such.factory"}}}, "karni.E590"),
        ({"KARNI_API_UNVERSIONED": "hide", "KARNI_API_VERSION": "v1"}, "karni.E591"),
        ({"KARNI_API_UNVERSIONED": "redirect", "KARNI_API_VERSION": ""}, "karni.E591"),
        (
            {"KARNI_API_VERSIONS": {"v0": {"deprecated": True, "sunset": "2020-01-01"}}},
            "karni.W660",
        ),
    ],
)
def test_the_check_reports_each_problem(settings: Any, changes: dict[str, Any], code: str) -> None:
    for name, value in changes.items():
        setattr(settings, name, value)
    assert code in _ids(check_api_versions())


def test_the_check_is_quiet_for_good_settings(settings: Any) -> None:
    settings.KARNI_API_VERSION = "v2"
    settings.KARNI_API_VERSIONS = {
        "v1": {"deprecated": "2026-06-01", "sunset": "2999-01-31", "notes": "/migrate/"},
    }
    settings.KARNI_API_UNVERSIONED = "redirect"
    assert check_api_versions() == []


def test_a_bad_setting_stops_the_urls_with_its_code(settings: Any) -> None:
    settings.KARNI_API_VERSION = "v1"
    settings.KARNI_API_UNVERSIONED = "hide"
    with pytest.raises(ImproperlyConfigured, match="E591"):
        api_urls()


def test_the_default_router_is_the_one_karni_api_urls_built() -> None:
    assert router is api_versions._router_for(ApiVersion("v1"))
