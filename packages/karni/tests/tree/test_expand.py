"""``?expand=parent`` on a tree resource, and ``?expand=category.parent`` through a relation.

A tree's ``parent`` is a forward foreign key to the same model, so it expands
like any other: one level, two levels, and through a relation. A parent the
requester cannot read renders as ``null``, like every expanded to-one
outside its target's read scope. The tree-scope side (``tree:<path>``) is in
``tests/treescope/test_api.py``.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from karni.testing import client_as
from tests.testapp.models import Category, Product, Region
from tests.tree.build import Regions, regions

pytestmark = pytest.mark.django_db


def ok(response: Any) -> Any:
    assert response.status_code == 200, response.content
    return response.json()


def by_name(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["name"]: row for row in rows}


@pytest.fixture
def tree() -> Regions:
    return regions()


def test_expand_parent_nests_the_parent(tree: Regions) -> None:
    rows = by_name(ok(client_as(None).get("/api/regions/", {"expand": "parent"}))["results"])
    france = rows["France"]["parent"]
    assert isinstance(france, dict) and france["name"] == "Europe"
    assert str(france["parent"]) == str(tree.world.pk)  # one level asked: the next is the key
    assert rows["World"]["parent"] is None  # a root has no parent


def test_expand_parent_parent_nests_two_levels(tree: Regions) -> None:
    data = ok(client_as(None).get(f"/api/regions/{tree.paris.pk}/", {"expand": "parent.parent"}))
    assert data["parent"]["name"] == "France"
    assert data["parent"]["parent"]["name"] == "Europe"
    assert str(data["parent"]["parent"]["parent"]) == str(tree.world.pk)


def test_the_query_count_does_not_grow_with_the_rows(tree: Regions) -> None:
    def count() -> int:
        with CaptureQueriesContext(connection) as captured:
            ok(client_as(None).get("/api/regions/", {"expand": "parent.parent"}))
        return len(captured)

    few = count()
    for index in range(12):
        Region.objects.create(name=f"Town {index}", parent=tree.paris)
    assert count() == few


def test_expand_through_a_relation_nests_the_parent() -> None:
    user = _user()
    everything = Category.objects.create(name="Everything")
    food = Category.objects.create(name="Food", parent=everything)
    Product.objects.create(name="Milk", category=food)
    client = client_as(user=user)
    row = ok(client.get("/api/products/", {"expand": "category.parent"}))["results"][0]
    assert row["category"]["name"] == "Food"
    assert row["category"]["parent"]["name"] == "Everything"
    assert row["category"]["parent"]["parent"] is None


def test_a_parent_outside_the_read_scope_renders_null(tree: Regions) -> None:
    # tests/tree/urls.py: the regions coded "secret" are not readable.
    tree.europe.code = "secret"
    tree.europe.save()
    with override_settings(
        ROOT_URLCONF="tests.tree.urls", KARNI_API_ROUTER="tests.tree.urls.get_router"
    ):
        client = client_as(None)
        rows = by_name(ok(client.get("/api/regions/", {"expand": "parent"}))["results"])
        assert "Europe" not in rows
        assert rows["France"]["parent"] is None
        assert rows["Paris"]["parent"]["name"] == "France"
        two = ok(client.get(f"/api/regions/{tree.paris.pk}/", {"expand": "parent.parent"}))
        assert two["parent"]["name"] == "France"
        assert two["parent"]["parent"] is None


def _user() -> Any:
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="reader@example.com", password="a-strong-password-123"
    )
