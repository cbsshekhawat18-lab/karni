"""The tree endpoints: tree/, children/, ancestors/, move/, the list filters and DELETE ?branch=.

The default routes serve ``regions`` (read by anyone, written by signed-in
users) and ``categories`` (the ordered tree, written by staff).
``tests/tree/urls.py`` serves the same models with narrowed access.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from karni.api.viewsets import BaseViewSet
from karni.testing import client_as
from tests.keys import missing_pk
from tests.testapp.models import Category, Region
from tests.testapp.viewsets import RegionViewSet, VenueViewSet
from tests.tree.build import Regions, regions

pytestmark = pytest.mark.django_db


def ok(response: Any) -> Any:
    assert response.status_code == 200, response.content
    return response.json()


def shape(nodes: list[dict[str, Any]]) -> list[Any]:
    """Names, nested: ``[name, [children...]]``, ``[name, None]`` where not loaded."""
    out: list[Any] = []
    for node in nodes:
        children = node["children"]
        out.append([node["name"], None if children is None else shape(children)])
    return out


def names(rows: list[dict[str, Any]]) -> list[str]:
    return [row["name"] for row in rows]


@pytest.fixture
def tree() -> Regions:
    return regions()


# tree/


def test_tree_answers_two_levels_and_says_what_has_children(tree: Regions) -> None:
    data = ok(client_as(None).get("/api/regions/tree/"))
    assert data["truncated"] is False
    assert shape(data["results"]) == [["World", [["Europe", None]]], ["Asia", []]]
    world = data["results"][0]
    assert world["has_children"] is True and world["children"][0]["has_children"] is True
    assert data["results"][1]["has_children"] is False
    assert world["id"] == str(tree.world.pk) or world["id"] == tree.world.pk


def test_tree_depth_and_root(tree: Regions) -> None:
    anyone = client_as(None)
    assert shape(ok(anyone.get("/api/regions/tree/?depth=1"))["results"]) == [
        ["World", None],
        ["Asia", []],
    ]
    deep = ok(anyone.get("/api/regions/tree/?depth=4"))["results"]
    assert shape(deep)[0] == [
        "World",
        [["Europe", [["France", [["Paris", []]]], ["Germany", [["Berlin", []]]]]]],
    ]
    below = ok(anyone.get(f"/api/regions/tree/?root={tree.europe.pk}&depth=1"))["results"]
    assert shape(below) == [["France", None], ["Germany", None]]
    below = ok(anyone.get(f"/api/regions/tree/?root={tree.europe.pk}"))["results"]
    assert shape(below) == [["France", [["Paris", []]]], ["Germany", [["Berlin", []]]]]
    leaf = ok(anyone.get(f"/api/regions/tree/?root={tree.paris.pk}"))
    assert leaf == {"results": [], "truncated": False}


def test_tree_parameters_are_checked(tree: Regions) -> None:
    anyone = client_as(None)
    for depth in ("0", "11", "two"):
        response = anyone.get(f"/api/regions/tree/?depth={depth}")
        assert response.status_code == 400
        assert response.json()["depth"][0].startswith("E342")
    response = anyone.get("/api/regions/tree/?root=not-a-key")
    assert response.status_code == 400
    assert response.json()["root"][0].startswith("E342")
    assert anyone.get(f"/api/regions/tree/?root={missing_pk(Region)}").status_code == 404


# children/, ancestors/, the list filters


def test_children_are_paginated_tree_nodes_in_sibling_order(tree: Regions) -> None:
    data = ok(client_as(None).get(f"/api/regions/{tree.europe.pk}/children/"))
    assert data["count"] == 2
    assert names(data["results"]) == ["France", "Germany"]
    assert all(row["has_children"] is True and row["children"] is None for row in data["results"])
    leaf = ok(client_as(None).get(f"/api/regions/{tree.paris.pk}/children/"))
    assert leaf["count"] == 0


def test_ancestors_come_root_first(tree: Regions) -> None:
    rows = ok(client_as(None).get(f"/api/regions/{tree.berlin.pk}/ancestors/"))
    assert names(rows) == ["World", "Europe", "Germany"]
    assert all("has_children" in row for row in rows)
    assert ok(client_as(None).get(f"/api/regions/{tree.world.pk}/ancestors/")) == []


def test_the_list_filters_by_parent_and_branch(tree: Regions) -> None:
    anyone = client_as(None)
    roots = ok(anyone.get("/api/regions/?parent=null"))["results"]
    assert set(names(roots)) == {"World", "Asia"}
    below = ok(anyone.get(f"/api/regions/?parent={tree.europe.pk}"))["results"]
    assert set(names(below)) == {"France", "Germany"}
    response = anyone.get("/api/regions/?parent=not-a-key")
    assert response.status_code == 400 and response.json()["parent"][0].startswith("E342")
    branch = ok(anyone.get(f"/api/regions/?descendants_of={tree.europe.pk}"))["results"]
    assert set(names(branch)) == {"France", "Paris", "Germany", "Berlin"}
    narrowed = ok(anyone.get(f"/api/regions/?descendants_of={tree.europe.pk}&name__icontains=er"))
    assert set(names(narrowed["results"])) == {"Germany", "Berlin"}


def test_a_flat_resource_has_no_tree_routes() -> None:
    assert not {"tree", "children", "ancestors", "move"} & {
        extra.__name__ for extra in VenueViewSet.get_extra_actions()
    }
    assert {"tree", "children", "ancestors", "move"} <= {
        extra.__name__ for extra in RegionViewSet.get_extra_actions()
    }
    assert RegionViewSet.serves_tree() and not VenueViewSet.serves_tree()
    assert not BaseViewSet.serves_tree()
    assert client_as(None).get("/api/venues/tree/").status_code == 404


# move/


def test_move_reparents_and_refuses_a_cycle(tree: Regions) -> None:
    assert client_as(None).post(
        f"/api/regions/{tree.germany.pk}/move/", {"parent": None}, format="json"
    ).status_code in (401, 403)
    me = client_as()
    url = f"/api/regions/{tree.germany.pk}/move/"
    moved = ok(me.post(url, {"parent": str(tree.asia.pk)}, format="json"))
    assert moved["name"] == "Germany" and moved["has_children"] is True
    assert Region.objects.get(pk=tree.germany.pk).parent_id == tree.asia.pk
    response = me.post(
        f"/api/regions/{tree.asia.pk}/move/", {"parent": str(tree.berlin.pk)}, format="json"
    )
    assert response.status_code == 400
    assert response.json()["parent"][0].startswith("E340")
    response = me.post(
        f"/api/regions/{tree.asia.pk}/move/", {"parent": str(missing_pk(Region))}, format="json"
    )
    assert response.status_code == 400 and response.json()["parent"][0].startswith("E342")
    response = me.post(
        f"/api/regions/{tree.asia.pk}/move/", {"parent": None, "position": 0}, format="json"
    )
    assert response.status_code == 400 and response.json()["position"][0].startswith("E343")
    root = ok(me.post(f"/api/regions/{tree.germany.pk}/move/", {"parent": None}, format="json"))
    assert root["parent"] is None


def test_move_places_an_ordered_node_for_staff_only() -> None:
    shoes = Category.objects.create(name="Shoes")
    boots = Category.objects.create(name="Boots", parent=shoes)
    clogs = Category.objects.create(name="Clogs", parent=shoes)
    staff = client_as("staff")
    moved = ok(
        staff.post(
            f"/api/categories/{clogs.pk}/move/",
            {"parent": str(shoes.pk), "position": 0},
            format="json",
        )
    )
    assert moved["position"] == 0
    assert [row.name for row in Category.objects.children(shoes)] == ["Clogs", "Boots"]
    refused = client_as().post(f"/api/categories/{boots.pk}/move/", {"parent": None}, format="json")
    assert refused.status_code == 403
    # position is the server's: the create body cannot set it
    body = {"name": "Sandals", "parent": str(shoes.pk), "position": 0}
    created = staff.post("/api/categories/", body, format="json")
    assert created.status_code == 201, created.content
    assert created.json()["position"] == 2


# DELETE and ?branch=true


def test_delete_refuses_a_node_with_children_and_deletes_a_branch_on_request(
    tree: Regions,
) -> None:
    me = client_as()
    response = me.delete(f"/api/regions/{tree.europe.pk}/")
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "E341" and body["conflict"] == {"children": 2}
    response = me.delete(f"/api/regions/{tree.europe.pk}/?branch=maybe")
    assert response.status_code == 400 and response.json()["branch"][0].startswith("E342")
    assert me.delete(f"/api/regions/{tree.europe.pk}/?branch=true").status_code == 204
    data = ok(client_as(None).get("/api/regions/tree/?depth=3"))
    assert shape(data["results"]) == [["World", []], ["Asia", []]]
    assert me.delete(f"/api/regions/{tree.asia.pk}/").status_code == 204


def test_a_soft_deleted_node_hides_its_branch_everywhere(tree: Regions) -> None:
    Region.objects.filter(pk=tree.germany.pk).delete()  # Berlin stays live below it
    anyone = client_as(None)
    below = ok(anyone.get(f"/api/regions/tree/?root={tree.europe.pk}&depth=3"))["results"]
    assert shape(below) == [["France", [["Paris", []]]]]
    branch = ok(anyone.get(f"/api/regions/?descendants_of={tree.europe.pk}"))["results"]
    assert set(names(branch)) == {"France", "Paris"}
    assert ok(anyone.get(f"/api/regions/{tree.berlin.pk}/ancestors/")) == []


# access (tests/tree/urls.py)


@pytest.fixture
def scoped() -> Iterator[None]:
    with override_settings(
        ROOT_URLCONF="tests.tree.urls", KARNI_API_ROUTER="tests.tree.urls.get_router"
    ):
        yield


def test_tree_endpoints_show_only_what_the_requester_reads(tree: Regions, scoped: None) -> None:
    Region.objects.filter(pk=tree.europe.pk).update(code="secret")
    anyone = client_as(None)
    data = ok(anyone.get("/api/regions/tree/?depth=2"))
    # Europe is out of scope: World keeps no child, and France and Germany, whose parent
    # is live but unreadable, start the requester's tree.
    assert shape(data["results"]) == [
        ["World", []],
        ["France", [["Paris", []]]],
        ["Germany", [["Berlin", []]]],
        ["Asia", []],
    ]
    assert data["results"][0]["has_children"] is False
    assert anyone.get(f"/api/regions/tree/?root={tree.europe.pk}").status_code == 404
    assert anyone.get(f"/api/regions/{tree.europe.pk}/children/").status_code == 404
    assert anyone.get(f"/api/regions/{tree.europe.pk}/ancestors/").status_code == 404
    assert names(ok(anyone.get(f"/api/regions/{tree.paris.pk}/ancestors/"))) == ["France"]
    branch = ok(anyone.get(f"/api/regions/?descendants_of={tree.world.pk}"))["results"]
    assert branch == []  # the walk stops at Europe
    assert ok(anyone.get(f"/api/regions/?descendants_of={tree.europe.pk}"))["results"] == []


def test_move_needs_write_access_and_a_readable_parent(tree: Regions, scoped: None) -> None:
    Region.objects.filter(pk=tree.asia.pk).update(code="secret")
    Region.objects.filter(pk=tree.paris.pk).update(code="locked")
    me = client_as()
    response = me.post(f"/api/regions/{tree.paris.pk}/move/", {"parent": None}, format="json")
    assert response.status_code == 403
    response = me.post(
        f"/api/regions/{tree.berlin.pk}/move/", {"parent": str(tree.asia.pk)}, format="json"
    )
    assert response.status_code == 400 and response.json()["parent"][0].startswith("E342")


def test_a_branch_delete_needs_write_access_to_every_node(tree: Regions, scoped: None) -> None:
    Region.objects.filter(pk=tree.paris.pk).update(code="locked")
    me = client_as()
    assert me.delete(f"/api/regions/{tree.europe.pk}/?branch=true").status_code == 403
    assert Region.objects.descendants(tree.europe).count() == 4
    assert me.delete(f"/api/regions/{tree.germany.pk}/?branch=true").status_code == 204
    assert not Region.objects.filter(pk=tree.berlin.pk).exists()


def test_the_node_limit_drops_whole_levels(tree: Regions, scoped: None) -> None:
    anyone = client_as(None)
    data = ok(anyone.get("/api/small-regions/tree/?depth=3"))
    # 2 roots + Europe fit in 4 nodes, France and Germany would make 5.
    assert data["truncated"] is True
    assert shape(data["results"]) == [["World", [["Europe", None]]], ["Asia", []]]
    for number in range(4):
        Region.objects.create(name=f"Root {number}")
    data = ok(anyone.get("/api/small-regions/tree/"))
    assert data["truncated"] is True
    assert names(data["results"]) == ["World", "Asia", "Root 0", "Root 1"]
    assert shape(data["results"])[0] == ["World", None]


# query counts


def count_queries(client: Any, url: str) -> int:
    with CaptureQueriesContext(connection) as queries:
        ok(client.get(url))
    return len(queries.captured_queries)


def test_query_counts_do_not_grow_with_the_tree(tree: Regions) -> None:
    anyone = client_as(None)
    urls = [
        "/api/regions/tree/?depth=3",
        f"/api/regions/tree/?root={tree.world.pk}&depth=3",
        f"/api/regions/{tree.europe.pk}/children/",
        f"/api/regions/{tree.berlin.pk}/ancestors/",
        f"/api/regions/?descendants_of={tree.world.pk}",
    ]
    before = [count_queries(anyone, url) for url in urls]
    for number in range(12):
        country = Region.objects.create(name=f"Country {number}", parent=tree.europe)
        Region.objects.create(name=f"City {number}", parent=country)
        Region.objects.create(name=f"Root {number}")
    deeper = tree.berlin
    for number in range(6):
        deeper = Region.objects.create(name=f"District {number}", parent=deeper)
    after = [count_queries(anyone, url) for url in urls[:3]]
    after.append(count_queries(anyone, f"/api/regions/{deeper.pk}/ancestors/"))
    after.append(count_queries(anyone, urls[4]))
    assert after == before
