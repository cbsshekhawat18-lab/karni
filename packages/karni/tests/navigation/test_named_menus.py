"""Named menus: ``KARNI_NAVIGATION`` as ``{"app": [...], "public": [...]}``.

A list is the ``app`` menu, a mapping holds several, and ``GET
/api/navigation/?menu=`` answers one. A name the project does not declare
answers an empty menu.
"""

from __future__ import annotations

from types import ModuleType
from typing import Any

import pytest
from django.urls import include, path
from pytest_django import Settings
from rest_framework.test import APIClient

from karni import navigation
from karni.navigation.api import build_urlpatterns
from karni.navigation.checks import check_navigation

pytestmark = pytest.mark.django_db

MENUS: dict[str, list[dict[str, Any]]] = {
    "app": [{"label": "Orders", "route": "/orders", "requires": "authenticated"}],
    "public": [
        {"label": "Shop", "route": "/shop", "requires": "public"},
        {"label": "Wishlist", "route": "/shop/wishlist"},
    ],
    "account": [{"label": "Your orders", "route": "/orders"}],
}


def _urlconf() -> ModuleType:
    module = ModuleType("named_menu_urls")
    module.__dict__["urlpatterns"] = [path("api/", include(build_urlpatterns()))]
    return module


@pytest.fixture(autouse=True)
def _menus(settings: Settings) -> None:
    settings.KARNI_NAVIGATION = MENUS
    settings.ROOT_URLCONF = _urlconf()


def _labels(response: Any) -> list[str]:
    assert response.status_code == 200, response.content
    return [item["label"] for item in response.json()["items"]]


def test_the_app_menu_is_the_default() -> None:
    assert navigation.menus() == ["app", "public", "account"]
    assert _labels(APIClient().get("/api/navigation/")) == []  # Orders needs a sign-in


def test_a_visitor_gets_the_public_entries_of_the_public_menu() -> None:
    assert _labels(APIClient().get("/api/navigation/?menu=public")) == ["Shop"]


def test_a_signed_in_user_gets_each_menu(django_user_model: Any) -> None:
    client = APIClient()
    client.force_authenticate(django_user_model.objects.create_user("ana@example.com", "pw"))
    assert _labels(client.get("/api/navigation/?menu=app")) == ["Orders"]
    assert _labels(client.get("/api/navigation/?menu=public")) == ["Shop", "Wishlist"]
    assert _labels(client.get("/api/navigation/?menu=account")) == ["Your orders"]


def test_a_menu_the_project_does_not_name_is_empty() -> None:
    assert _labels(APIClient().get("/api/navigation/?menu=footer")) == []


def test_a_list_is_the_app_menu_alone(settings: Settings) -> None:
    settings.KARNI_NAVIGATION = MENUS["public"]
    assert navigation.menus() == ["app"]
    assert [node.label for node in navigation.load_nodes("app")] == ["Shop", "Wishlist"]
    assert navigation.load_nodes("public") == ()


def test_a_bad_menu_name_or_value_is_a_problem() -> None:
    problems = navigation.settings_problems({"Main Menu": [], "public": "x"})
    assert any("names the menu 'Main Menu'" in problem for problem in problems)
    assert any("['public'] = 'x' must be a list" in problem for problem in problems)
    nested = navigation.settings_problems({"public": [{"label": "No route"}]})
    assert nested and "['public'][0]" in nested[0]


def test_karni_check_compares_every_menu() -> None:
    messages = check_navigation(routes=["/orders", "/shop"])
    found = [message.msg for message in messages if message.id == "karni.E533"]
    assert len(found) == 1
    assert found[0].startswith(
        "Navigation item 'public menu > Wishlist' links to /shop/wishlist, which no page of "
        "the frontend serves."
    )
