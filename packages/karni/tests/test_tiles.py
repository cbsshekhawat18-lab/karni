"""karni.tiles: home tiles per role, from code and from the setting karni.yaml writes."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from karni import tiles
from karni.accounts.roles import sync_roles
from karni.exceptions import KarniImproperlyConfigured
from karni.testing import user_with_roles

pytestmark = pytest.mark.django_db

ROLES = {
    "admin": {"name": "Admin", "system": True, "grants": {"*": "all"}},
    "clerk": {"name": "Clerk", "grants": {"testapp.event:view": "all"}},
    "member": {"name": "Member", "grants": {}},
}


@pytest.fixture(autouse=True)
def roles() -> Iterator[None]:
    with override_settings(KARNI_ROLES=ROLES):
        sync_roles()
        yield


@pytest.fixture
def revenue() -> Iterator[Any]:
    calls: list[Any] = []

    @tiles.register(key="tests.revenue", title="Revenue", requires="testapp.event:view", order=2)
    def figures(request: Any) -> dict[str, Any]:
        calls.append(request)
        return tiles.Tile.stat_values(
            [("Today", Decimal("12.5"), "money"), ("Orders", 3, "number", "/orders")],
            currency="EUR",
        )

    yield calls
    tiles.unregister("tests.revenue")


def get(user: Any) -> list[dict[str, Any]]:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    answer = client.get("/api/dashboard/")
    assert answer.status_code == 200, answer.content
    return list(answer.json()["tiles"])


def test_a_code_tile_reaches_the_roles_it_requires_with_its_figures(revenue: Any) -> None:
    [tile] = get(user_with_roles("clerk"))
    assert (tile["key"], tile["title"], tile["kind"], tile["resource"]) == (
        "tests.revenue",
        "Revenue",
        "stat",
        None,
    )
    assert tile["data"] == {
        "currency": "EUR",
        "values": [
            {"label": "Today", "value": "12.50", "format": "money", "link": None},
            {"label": "Orders", "value": 3, "format": "number", "link": "/orders"},
        ],
    }
    assert get(user_with_roles("member")) == []
    assert get(None) == []
    assert len(revenue) == 1  # a role that does not see a tile never computes it


@override_settings(
    KARNI_DASHBOARD_TILES=[
        {
            "key": "tests.drafts",
            "title": "Drafts",
            "kind": "stat",
            "resource": "events",
            "filters": {"status": "draft"},
            "requires": "testapp.event:view",
            "order": 1,
        },
        {"key": "tests.revenue", "title": "Takings", "roles": ["admin"]},
        {"key": "tests.welcome", "title": "Welcome", "resource": "events", "roles": ["member"]},
    ]
)
def test_the_setting_adds_resource_tiles_and_places_code_tiles(revenue: Any) -> None:
    clerk = get(user_with_roles("clerk"))
    assert [tile["key"] for tile in clerk] == ["tests.drafts"]
    assert (clerk[0]["resource"], clerk[0]["filters"], clerk[0]["data"]) == (
        "events",
        {"status": "draft"},
        None,
    )
    admin = get(user_with_roles("admin"))
    assert [(tile["key"], tile["title"]) for tile in admin] == [
        ("tests.drafts", "Drafts"),
        ("tests.revenue", "Takings"),
    ]
    assert [tile["key"] for tile in get(user_with_roles("member"))] == ["tests.welcome"]


@override_settings(KARNI_DASHBOARD_TILES=[{"key": "tests.revenue", "hidden": True}])
def test_hidden_takes_a_code_tile_off_the_home(revenue: Any) -> None:
    assert get(user_with_roles("admin")) == []


def test_a_tile_whose_code_answers_none_is_left_out() -> None:
    @tiles.register(key="tests.nothing")
    def nothing(request: Any) -> None:
        return None

    try:
        assert get(user_with_roles("admin")) == []
    finally:
        tiles.unregister("tests.nothing")


@pytest.mark.parametrize(
    "entry",
    [
        {"key": "tests.x", "title": "X"},  # neither code nor a resource
        {"key": "tests.x", "resource": "events", "kind": "pie"},
        {"key": "tests.x", "resource": "events", "size": "huge"},
        {"key": "tests.x", "resource": "events", "colour": "red"},
    ],
)
def test_a_tile_that_cannot_work_is_refused(entry: dict[str, Any]) -> None:
    with override_settings(KARNI_DASHBOARD_TILES=[entry]), pytest.raises(KarniImproperlyConfigured):
        tiles.all_tiles()
