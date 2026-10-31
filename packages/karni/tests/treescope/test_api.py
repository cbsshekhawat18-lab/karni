"""The tree scope through the API: list, detail, a custom action, export, imports and access/."""

from __future__ import annotations

import csv
import io
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from karni.accounts import grants
from karni.testing import client_as
from karni.transfer.services import PREVIEW, create_job, run_stage
from tests.testapp.models import Category, Listing, Product
from tests.transfer.conftest import api_request, csv_file
from tests.treescope import LISTING_VIEW, PRODUCT_VIEW
from tests.treescope.conftest import Catalog, fresh, make_user

pytestmark = pytest.mark.django_db


def ok(response: Any) -> Any:
    assert response.status_code == 200, response.content
    return response.json()


def names(rows: list[dict[str, Any]], key: str = "name") -> list[str]:
    return sorted(row[key] for row in rows)


def holder(
    catalog: Catalog,
    *nodes: Any,
    permission: str = PRODUCT_VIEW,
    scope: str = "tree:category",
    email: str = "",
) -> Any:
    """A user with one user grant of ``scope`` on ``nodes`` (and no role)."""
    user = make_user(email or f"holder{len(nodes)}{nodes[0].pk}@example.com")
    grants.grant(None, user, permission, scope, targets=[node.pk for node in nodes])
    return fresh(user)


def shape(nodes: list[dict[str, Any]]) -> list[Any]:
    """``[label, granted, [children...]]``, ``None`` where the children are not loaded."""
    return [
        [
            node["label"],
            node["granted"],
            None if node["children"] is None else shape(node["children"]),
        ]
        for node in nodes
    ]


class TestReads:
    def test_the_list_holds_the_rows_under_the_granted_nodes(self, catalog: Catalog) -> None:
        user = holder(catalog, catalog.food, catalog.books)
        rows = ok(client_as(user=user).get("/api/products/"))["results"]
        assert names(rows) == ["Apple pie", "Milk", "Novel"]

    def test_detail_answers_404_outside_the_subtree(self, catalog: Catalog) -> None:
        client = client_as(user=holder(catalog, catalog.food))
        assert ok(client.get(f"/api/products/{catalog.milk.pk}/"))["name"] == "Milk"
        assert client.get(f"/api/products/{catalog.saw.pk}/").status_code == 404

    def test_a_custom_action_reads_through_the_scope(self, catalog: Catalog) -> None:
        client = client_as(user=holder(catalog, catalog.fruit))
        assert ok(client.get(f"/api/products/{catalog.pie.pk}/card/")) == {"name": "Apple pie"}
        assert client.get(f"/api/products/{catalog.milk.pk}/card/").status_code == 404

    def test_a_write_is_403_on_a_row_readable_but_not_writable(self, catalog: Catalog) -> None:
        user = make_user("writer@example.com", "buyer")
        grants.grant(None, user, PRODUCT_VIEW, "tree:category", targets=[catalog.everything.pk])
        user = fresh(user, category=catalog.dairy)  # change: the role's node only
        client = client_as(user=user)
        changed = client.patch(f"/api/products/{catalog.milk.pk}/", {"name": "Oat milk"})
        assert changed.status_code == 200, changed.content
        assert client.patch(f"/api/products/{catalog.saw.pk}/", {"name": "x"}).status_code == 403

    def test_a_path_through_a_relation(self, catalog: Catalog) -> None:
        user = holder(
            catalog, catalog.tools, permission=LISTING_VIEW, scope="tree:product__category"
        )
        rows = ok(client_as(user=user).get("/api/listings/"))["results"]
        assert names(rows, "title") == ["Saw listing"]

    def test_a_role_grant_through_user_attribute(self, catalog: Catalog) -> None:
        user = fresh(make_user("buyer@example.com", "buyer"), category=catalog.food)
        rows = ok(client_as(user=user).get("/api/listings/"))["results"]
        assert names(rows, "title") == ["Apple pie listing", "Milk listing"]

    def test_where_tree_scope(self, catalog: Catalog) -> None:
        user = holder(catalog, catalog.tools)
        rows = ok(client_as(user=user).get("/api/where-products/"))["results"]
        assert names(rows) == ["Saw"]
        nobody = client_as(user=make_user("no-node@example.com"))
        assert ok(nobody.get("/api/where-products/"))["results"] == []
        assert client_as(None).get("/api/where-products/").status_code == 401

    def test_no_grant_no_rows(self, catalog: Catalog) -> None:
        user = make_user("nobody@example.com")
        grants.grant(None, user, PRODUCT_VIEW, "tree:category")  # no targets, no user.category
        response = client_as(user=fresh(user)).get("/api/products/")
        assert ok(response)["results"] == []

    def test_the_list_query_count_stays_flat(self, catalog: Catalog) -> None:
        def count(user: Any) -> int:
            client = client_as(user=user)
            with CaptureQueriesContext(connection) as captured:
                ok(client.get("/api/products/"))
            return len(captured)

        one = count(holder(catalog, catalog.apples, email="one@example.com"))
        for index in range(12):
            Product.objects.create(name=f"Extra {index}", category=catalog.saws)
        many = count(
            holder(catalog, catalog.food, catalog.tools, catalog.books, email="many@example.com")
        )
        assert many == one


class TestExportAndImport:
    def test_the_export_holds_the_scoped_rows(self, catalog: Catalog) -> None:
        response = client_as(user=holder(catalog, catalog.food)).get(
            "/api/products/export/?format=csv"
        )
        assert response.status_code == 200
        text = b"".join(response.streaming_content).decode() if response.streaming else ""
        text = text or response.content.decode()
        rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
        assert sorted(row["name"] for row in rows) == ["Apple pie", "Milk"]

    def test_an_import_names_only_the_products_in_the_subtree(self, catalog: Catalog) -> None:
        user = fresh(make_user("importer@example.com", "buyer"), category=catalog.tools)
        request = api_request("post", "/api/listings/import/", user)
        upload = csv_file(
            "listings.csv", [["title", "product"], ["Mine", "Saw"], ["Not mine", "Milk"]]
        )
        job = run_stage(create_job(Listing, request, upload), PREVIEW, user)
        assert job.result["created"] == 1 and job.result["errors"] == 1
        problem = job.problems[0]
        assert problem["row"] == 3 and "not visible to you" in problem["message"]


class TestAccessForest:
    def test_granted_nodes_their_ancestors_and_every_root(self, catalog: Catalog) -> None:
        user = holder(catalog, catalog.fruit, catalog.apples, catalog.saws)
        data = ok(client_as(user=user).get("/api/categories/access/"))
        assert data["all"] is False and data["truncated"] is False
        assert shape(data["results"]) == [
            [
                "Everything",
                False,
                [["Food", False, [["Fruit", True, None]]], ["Tools", False, [["Saws", True, []]]]],
            ],
            ["Books", False, []],
        ]
        fruit = data["results"][0]["children"][0]["children"][0]
        assert (
            fruit["has_children"] is True
            and fruit["parent"] == data["results"][0]["children"][0]["id"]
        )
        assert data["results"][1]["has_children"] is False

    def test_a_granted_node_below_another_is_inside_it(self, catalog: Catalog) -> None:
        user = holder(catalog, catalog.apples, catalog.food)
        data = ok(client_as(user=user).get("/api/categories/access/"))
        assert shape(data["results"])[0] == ["Everything", False, [["Food", True, None]]]

    def test_the_permission_parameter(self, catalog: Catalog) -> None:
        user = make_user("two@example.com")
        grants.grant(None, user, PRODUCT_VIEW, "tree:category", targets=[catalog.books.pk])
        grants.grant(None, user, LISTING_VIEW, "tree:product__category", targets=[catalog.saws.pk])
        client = client_as(user=fresh(user))
        both = ok(client.get("/api/categories/access/"))
        assert sorted(both_granted(both)) == ["Books", "Saws"]
        only = ok(client.get(f"/api/categories/access/?permission={LISTING_VIEW}"))
        assert both_granted(only) == ["Saws"]
        bad = client.get("/api/categories/access/?permission=products")
        assert bad.status_code == 400 and "E491" in str(bad.json())

    def test_a_holder_of_every_row_holds_every_root(self, catalog: Catalog) -> None:
        ops = make_user("ops@example.com", "ops")
        data = ok(client_as(user=ops).get(f"/api/categories/access/?permission={PRODUCT_VIEW}"))
        assert data["all"] is True
        assert [(n["label"], n["granted"]) for n in data["results"]] == [
            ("Everything", True),
            ("Books", True),
        ]
        root = make_user("root@example.com", is_superuser=True)
        assert ok(client_as(user=root).get("/api/categories/access/"))["all"] is True

    def test_anonymous_is_refused_and_no_grant_lists_the_roots(self, catalog: Catalog) -> None:
        assert client_as(None).get("/api/categories/access/").status_code in (401, 403)
        nobody = make_user("plain@example.com")
        data = ok(client_as(user=nobody).get("/api/categories/access/"))
        assert shape(data["results"]) == [["Everything", False, []], ["Books", False, []]]

    def test_a_cycle_in_the_data_never_loops(self, catalog: Catalog) -> None:
        Category.objects.filter(pk=catalog.food.pk).update(parent=catalog.apples)
        user = holder(catalog, catalog.fruit)
        data = ok(client_as(user=user).get("/api/categories/access/"))
        seen = both_granted(data)
        assert seen == ["Fruit"]
        assert {node["label"] for node in data["results"]} >= {"Everything", "Books"}

    def test_the_region_forest_follows_the_many_to_many(self, catalog: Catalog) -> None:
        user = make_user("regions@example.com")
        grants.grant(None, user, PRODUCT_VIEW, "tree:regions", targets=[catalog.lyon.pk])
        data = ok(client_as(user=fresh(user)).get("/api/regions/access/"))
        assert shape(data["results"]) == [
            ["World", False, [["Europe", False, [["France", False, [["Lyon", True, []]]]]]]],
            ["Asia", False, []],
        ]

    def test_the_query_count_does_not_grow_with_the_nodes(self, catalog: Catalog) -> None:
        def count(user: Any) -> int:
            client = client_as(user=user)
            with CaptureQueriesContext(connection) as captured:
                ok(client.get("/api/categories/access/"))
            return len(captured)

        one = count(holder(catalog, catalog.apples, email="one@example.com"))
        three = count(
            holder(catalog, catalog.apples, catalog.saws, catalog.books, email="three@example.com")
        )
        assert three == one

    def test_the_root_limit_says_truncated(self, catalog: Catalog, monkeypatch: Any) -> None:
        from tests.treescope import ForestCategoryViewSet

        for index in range(5):
            Category.objects.create(name=f"Extra root {index}")
        monkeypatch.setattr(ForestCategoryViewSet, "tree_max_nodes", 6)
        user = holder(catalog, catalog.saws)
        data = ok(client_as(user=user).get("/api/categories/access/"))
        assert data["truncated"] is True
        assert both_granted(data) == ["Saws"]  # a granted path is never cut
        assert len(data["results"]) == 4  # Everything (3 nodes) and 3 more roots


def both_granted(data: dict[str, Any]) -> list[str]:
    found: list[str] = []
    stack = list(data["results"])
    while stack:
        node = stack.pop()
        if node["granted"]:
            found.append(node["label"])
        stack.extend(node["children"] or [])
    return sorted(found)
