"""``GET /api/navigation/`` (experimental): the menu over HTTP, in both auth modes, and its schema.

The URLconf is built in this module after ``KARNI_NAVIGATION`` is set, the
way ``karni.api.urls`` builds it at import. Clients sign in for real (a JWT
access token, or a session), so each request loads its own user and grants.
"""

from __future__ import annotations

from types import ModuleType
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import include, path
from drf_spectacular.generators import SchemaGenerator
from pytest_django import Settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from karni.errorcodes import get as get_code
from karni.navigation.api import build_urlpatterns

from .conftest import MENU, make_user, store

pytestmark = pytest.mark.django_db

URL = "/api/navigation/"


def _urlconf() -> ModuleType:
    module = ModuleType("navigation_urls")
    module.__dict__["urlpatterns"] = [path("api/", include(build_urlpatterns()))]
    return module


@pytest.fixture(autouse=True)
def _world(settings: Settings, roles: None) -> None:
    settings.KARNI_NAVIGATION = MENU
    settings.KARNI_AUTH_MODE = "jwt"
    settings.ROOT_URLCONF = _urlconf()


def _bearer(user: Any) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def _labels(body: dict[str, Any]) -> list[Any]:
    return [
        item["label"] if item["route"] else (item["label"], _labels({"items": item["children"]}))
        for item in body["items"]
    ]


def test_a_visitor_gets_the_public_entries() -> None:
    response = APIClient().get(URL)
    assert response.status_code == 200, response.content
    assert response.json() == {
        "items": [{"label": "Home", "icon": "home", "route": "/", "children": []}]
    }


def test_each_user_gets_their_own_menu_with_a_token() -> None:
    editor = make_user("editor@example.com", "catalog_editor")
    organizer = make_user("organizer@example.com", "organizer")
    assert _labels(_bearer(editor).get(URL).json()) == [
        "Home",
        ("Catalog", ["Categories", "Products"]),
        "Account",
    ]
    assert _labels(_bearer(organizer).get(URL).json()) == ["Home", "Events", "Account"]


def test_a_session_user_gets_the_same_menu(settings: Settings) -> None:
    settings.KARNI_AUTH_MODE = "session"
    client = APIClient()
    client.force_login(make_user("organizer@example.com", "organizer"))
    assert _labels(client.get(URL).json()) == ["Home", "Events", "Account"]


def test_a_user_grant_opens_an_item_over_http(settings: Settings) -> None:
    from karni.accounts import grants

    settings.KARNI_USER_GRANTS = True
    reader = make_user("reader@example.com")
    client = _bearer(reader)
    assert "Regions" not in _labels(client.get(URL).json())
    grants.grant(None, reader, "testapp.region:view")
    assert "Regions" in _labels(client.get(URL).json())


def test_the_database_source_answers_the_same(settings: Settings) -> None:
    editor = make_user("editor@example.com", "catalog_editor")
    from_settings = _bearer(editor).get(URL).json()
    store(MENU)
    settings.KARNI_NAVIGATION = "db"
    assert _bearer(editor).get(URL).json() == from_settings


def test_the_request_costs_the_grants_and_the_rows(settings: Settings) -> None:
    client = APIClient()
    client.force_authenticate(make_user("editor@example.com", "catalog_editor"))
    with CaptureQueriesContext(connection) as queries:
        assert client.get(URL).status_code == 200
    assert len(queries) == 1  # the role grants
    store(MENU)
    settings.KARNI_NAVIGATION = "db"
    settings.KARNI_USER_GRANTS = True
    client.force_authenticate(make_user("other@example.com", "catalog_editor"))
    with CaptureQueriesContext(connection) as queries:
        assert client.get(URL).status_code == 200
    assert len(queries) == 3  # the rows, the role grants, the user grants


def test_no_route_while_the_setting_is_unset(settings: Settings) -> None:
    settings.KARNI_NAVIGATION = None
    settings.ROOT_URLCONF = _urlconf()
    assert APIClient().get(URL).status_code == 404
    assert build_urlpatterns() == []


def test_a_urlconf_built_while_on_answers_e535_once_off(settings: Settings) -> None:
    settings.KARNI_NAVIGATION = None
    response = APIClient().get(URL)
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "E535" and body["detail"].startswith("E535: ")
    assert get_code("E535") is not None


def test_writes_are_not_allowed() -> None:
    assert APIClient().post(URL, {}, format="json").status_code == 405


def test_the_openapi_schema_describes_the_menu() -> None:
    schema = SchemaGenerator(patterns=_urlconf().urlpatterns).get_schema(request=None, public=True)
    operation = schema["paths"]["/api/navigation/"]["get"]
    assert operation["operationId"] == "navigation"
    ok = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok == {"$ref": "#/components/schemas/Navigation"}
    components = schema["components"]["schemas"]
    assert components["Navigation"]["properties"]["items"]["items"] == {
        "$ref": "#/components/schemas/NavigationItem"
    }
    item = components["NavigationItem"]
    assert set(item["properties"]) == {"label", "icon", "route", "children"}
    assert set(item["required"]) == {"label", "icon", "route", "children"}
    assert item["properties"]["route"]["nullable"] is True
    assert item["properties"]["children"] == {
        "type": "array",
        "items": {"$ref": "#/components/schemas/NavigationItem"},
    }


def test_karni_api_urls_mounts_it_first_while_set(settings: Settings) -> None:
    import importlib

    import karni.api.urls as api_urls

    try:
        reloaded = importlib.reload(api_urls)
        assert reloaded.urlpatterns[0].name == "karni-navigation"
    finally:
        settings.KARNI_NAVIGATION = None
        importlib.reload(api_urls)
    assert all(getattr(p, "name", "") != "karni-navigation" for p in api_urls.urlpatterns)
