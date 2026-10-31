"""A taxonomy key as a ``tree:<path>`` scope, and its import and export columns."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from karni.accounts import grants
from karni.testing import client_as
from karni.transfer.services import COMMIT, PREVIEW, create_job, run_stage
from tests.taxoapp.models import Product
from tests.taxonomy.conftest import Catalog
from tests.transfer.conftest import api_request, csv_file

pytestmark = pytest.mark.django_db

VIEW = "taxoapp.product:view"


def ok(response: Any) -> Any:
    assert response.status_code == 200, response.content
    return response.json()


def names(data: Any) -> list[str]:
    return sorted(row["name"] for row in data["results"])


def user(email: str = "someone@example.com") -> Any:
    return get_user_model().objects.create_user(email=email, password="s3cret-pass-123")


# the tree scope


@pytest.fixture
def scoped(settings: Any) -> Iterator[None]:
    settings.KARNI_USER_GRANTS = True
    with override_settings(KARNI_API_ROUTER="tests.taxonomy.urls.get_scope_router"):
        yield


def holder(*nodes: Any) -> Any:
    """A user with one grant of the products under ``nodes`` (tree:region), and no role."""
    found = user(f"holder{nodes[0].pk}@example.com")
    grants.grant(None, found, VIEW, "tree:region", targets=[node.pk for node in nodes])
    return get_user_model().objects.get(pk=found.pk)


def test_a_granted_node_limits_the_tagged_rows(catalog: Catalog, scoped: None) -> None:
    client = client_as(user=holder(catalog.france))
    assert names(ok(client.get("/scoped/products/"))) == ["Pie", "Secret plan", "Wine"]
    client = client_as(user=holder(catalog.europe, catalog.japan))
    assert names(ok(client.get("/scoped/products/"))) == [
        "Ham",
        "Pie",
        "Saw",
        "Secret plan",
        "Sunk",
        "Wine",
    ]
    assert client_as(user=user()).get("/scoped/products/").status_code == 403  # no grant


def test_the_scope_and_the_taxonomy_filter_combine(catalog: Catalog, scoped: None) -> None:
    client = client_as(user=holder(catalog.europe))
    url = f"/scoped/products/?region={catalog.lyon.pk}"
    assert names(ok(client.get(url))) == ["Pie", "Wine"]
    url = f"/scoped/products/?region={catalog.asia.pk}&region_descendants=true"
    assert names(ok(client.get(url))) == []


def test_facets_count_only_the_rows_the_scope_reaches(catalog: Catalog, scoped: None) -> None:
    client = client_as(user=holder(catalog.france))
    data = ok(client.get("/scoped/products/facets/?taxonomy=region&rollup=true"))
    found = {row["label"]: row["count"] for row in data["results"]}
    assert found == {"World": 3, "Europe": 3, "France": 3, "Lyon": 2}


def test_a_detail_out_of_the_granted_subtree_is_a_404(catalog: Catalog, scoped: None) -> None:
    client = client_as(user=holder(catalog.france))
    assert client.get(f"/scoped/products/{catalog.wine.pk}/").status_code == 200
    assert client.get(f"/scoped/products/{catalog.saw.pk}/").status_code == 404


# import and export


def exported(client: Any, url: str) -> dict[str, dict[str, str]]:
    response = client.get(url)
    assert response.status_code == 200
    text = b"".join(response.streaming_content).decode() if response.streaming else ""
    text = text or response.content.decode()
    return {row["name"]: row for row in csv.DictReader(io.StringIO(text.lstrip("﻿")))}


def test_the_export_names_the_tags_by_natural_key(catalog: Catalog) -> None:
    rows = exported(client_as(None), "/api/products/export/?format=csv")
    assert sorted(rows["Wine"]["region"].split("|")) == ["fr", "ly"]
    assert rows["Wine"]["category"] == "food"
    assert rows["Loose"]["region"] == "" and rows["Loose"]["category"] == ""
    filtered = exported(
        client_as(None), f"/api/products/export/?format=csv&region={catalog.japan.pk}"
    )
    assert list(filtered) == ["Saw"]


def test_the_import_template_and_columns_describe_the_tags(catalog: Catalog) -> None:
    data = ok(client_as(user=user()).get("/api/products/import/"))
    fields = {field["name"]: field for field in data["fields"]}
    assert fields["region"]["kind"] == "relations"
    assert fields["region"]["target"] == "taxoapp.region" and fields["region"]["lookup"] == "code"
    assert fields["category"]["lookup"] == "slug"


def test_an_import_tags_rows_by_natural_key_and_reports_unknown_nodes(catalog: Catalog) -> None:
    importer = user("importer@example.com")
    request = api_request("post", "/api/products/import/", importer)
    upload = csv_file(
        "products.csv",
        [
            ["name", "price", "region", "category"],
            ["Tart", "3", "ly", "fruit"],
            ["Atlas", "9", "fr|jp", "tools|food"],
            ["Stray", "1", "ly|nowhere", ""],
            ["Lost", "1", "", "gadgets"],
            ["Wine", "4", "es", "food"],
        ],
    )
    job = run_stage(create_job(Product, request, upload), PREVIEW, importer)
    assert job.result["created"] == 2 and job.result["updated"] == 1, job.problems
    assert job.result["errors"] == 2
    problems = {(problem["row"], problem["field"]): problem["message"] for problem in job.problems}
    assert "no region with code 'nowhere'" in problems[(4, "region")]
    assert "no category with slug 'gadgets'" in problems[(5, "category")]
    assert not Product.objects.filter(name="Tart").exists()  # the preview wrote nothing
    run_stage(job, COMMIT, importer)
    atlas = Product.objects.get(name="Atlas")
    assert sorted(node.code for node in atlas.region.all()) == ["fr", "jp"]
    assert sorted(node.slug for node in atlas.category.all()) == ["food", "tools"]
    assert [node.code for node in Product.objects.get(name="Tart").region.all()] == ["ly"]
    assert [node.code for node in Product.objects.get(name="Wine").region.all()] == ["es"]
    assert not Product.objects.filter(name__in=["Stray", "Lost"]).exists()


def test_an_import_reads_a_hidden_node_as_unknown(catalog: Catalog) -> None:
    importer = user("hidden@example.com")
    request = api_request("post", "/api/products/import/", importer)
    upload = csv_file("products.csv", [["name", "region"], ["Ghost", "hidden"]])
    job = run_stage(create_job(Product, request, upload), PREVIEW, importer)
    assert job.result["errors"] == 1
    assert "no region with code 'hidden'" in job.problems[0]["message"]
