"""The taxonomy API: the list filters, facets/, <key>/tagged/ and the OpenAPI document.

``products`` hides the ``Secret plan`` product from everyone but staff, and
``regions`` hides the ``Hidden`` region (and so its branch) from everyone.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from karni.testing import client_as
from tests.taxoapp.models import Product, Region
from tests.taxonomy.conftest import Catalog

pytestmark = pytest.mark.django_db


def ok(response: Any) -> Any:
    assert response.status_code == 200, response.content
    return response.json()


def names(data: Any) -> list[str]:
    rows = data["results"] if isinstance(data, dict) else data
    return sorted(row["name"] for row in rows)


def counts(data: dict[str, Any]) -> dict[str, int]:
    return {row["label"]: row["count"] for row in data["results"]}


def refused(response: Any, param: str) -> str:
    assert response.status_code == 400, response.content
    message = str(response.json()[param][0])
    assert message.startswith("E573"), message
    return message


# the list filters


def test_a_node_filters_the_rows_tagged_with_it(catalog: Catalog) -> None:
    data = ok(client_as(None).get(f"/api/products/?region={catalog.france.pk}"))
    assert names(data) == ["Wine"]  # the secret one is out of the read scope


def test_several_nodes_read_the_rows_tagged_with_any_once(catalog: Catalog) -> None:
    ids = catalog.ids(catalog.france, catalog.lyon, catalog.japan)
    data = ok(client_as(None).get(f"/api/products/?region={ids}"))
    assert names(data) == ["Pie", "Saw", "Wine"]
    assert data["count"] == 3


def test_a_repeated_key_reads_like_a_list(catalog: Catalog) -> None:
    url = f"/api/products/?region={catalog.france.pk}&region={catalog.japan.pk}"
    assert names(ok(client_as(None).get(url))) == ["Saw", "Wine"]


def test_descendants_add_the_rows_tagged_under_the_nodes(catalog: Catalog) -> None:
    url = f"/api/products/?region={catalog.europe.pk}"
    assert names(ok(client_as(None).get(url))) == []
    data = ok(client_as(None).get(f"{url}&region_descendants=true"))
    # Sunk is tagged under Hidden, which the requester cannot read: its branch is hidden.
    assert names(data) == ["Ham", "Pie", "Wine"]
    assert names(ok(client_as("staff").get(f"{url}&region_descendants=true"))) == [
        "Ham",
        "Pie",
        "Secret plan",
        "Wine",
    ]


def test_descendants_false_is_the_plain_filter(catalog: Catalog) -> None:
    url = f"/api/products/?region={catalog.france.pk}&region_descendants=false"
    assert names(ok(client_as(None).get(url))) == ["Wine"]


def test_a_node_the_requester_cannot_read_matches_nothing(catalog: Catalog) -> None:
    assert names(ok(client_as(None).get(f"/api/products/?region={catalog.deep.pk}"))) == ["Sunk"]
    assert names(ok(client_as(None).get(f"/api/products/?region={catalog.hidden.pk}"))) == []
    url = f"/api/products/?region={catalog.hidden.pk}&region_descendants=true"
    assert names(ok(client_as(None).get(url))) == []


def test_the_filters_combine_with_the_others_and_each_other(catalog: Catalog) -> None:
    url = (
        f"/api/products/?region={catalog.europe.pk}&region_descendants=true"
        f"&category={catalog.food.pk}&category_descendants=true&name__icontains=i"
    )
    assert names(ok(client_as(None).get(url))) == ["Pie", "Wine"]


def test_the_adopted_field_filters_like_a_generated_one(catalog: Catalog) -> None:
    url = f"/api/suppliers/?region={catalog.world.pk}&region_descendants=true"
    assert names(ok(client_as(None).get(url))) == ["Acme", "Zen"]
    assert names(ok(client_as(None).get(f"/api/suppliers/?region={catalog.asia.pk}"))) == []


def test_a_bad_key_or_flag_is_a_400_with_e573(catalog: Catalog) -> None:
    message = refused(client_as(None).get("/api/products/?region=not-a-key"), "region")
    assert "'not-a-key' is not a key of Region" in message
    url = f"/api/products/?region={catalog.france.pk}&region_descendants=x"
    refused(client_as(None).get(url), "region_descendants")


def test_the_filter_is_one_statement_whatever_the_nodes(catalog: Catalog) -> None:
    client = client_as(None)
    url = f"/api/products/?region={catalog.world.pk}&region_descendants=true"
    with CaptureQueriesContext(connection) as few:
        ok(client.get(url))
    parent = catalog.japan
    for index in range(30):
        parent = Region.objects.create(name=f"Town {index}", code=f"t{index}", parent=parent)
    Product.objects.create(name="Far").region.set([parent])
    with CaptureQueriesContext(connection) as many:
        data = ok(client.get(url))
    assert "Far" in names(data)
    assert len(many) == len(few)
    walks = [query["sql"] for query in many.captured_queries if "RECURSIVE" in query["sql"]]
    assert len(walks) == 2  # the count and the page, each with the walk inside


# facets/


def test_facets_count_the_rows_tagged_with_each_node(catalog: Catalog) -> None:
    data = ok(client_as(None).get("/api/products/facets/?taxonomy=region"))
    assert data["taxonomy"] == "region" and data["rollup"] is False
    # Deep is readable, though its parent is not: it counts on its own.
    assert counts(data) == {"France": 1, "Lyon": 2, "Spain": 1, "Japan": 1, "Deep": 1}
    france = next(row for row in data["results"] if row["label"] == "France")
    assert france["id"] == catalog.france.pk or str(france["id"]) == str(catalog.france.pk)
    assert str(france["parent"]) == str(catalog.europe.pk)


def test_facets_roll_up_to_the_ancestors_counting_each_row_once(catalog: Catalog) -> None:
    data = ok(client_as(None).get("/api/products/facets/?taxonomy=region&rollup=true"))
    assert data["rollup"] is True
    # Sunk is tagged with Deep, below the unreadable Hidden: it rolls up to Deep only.
    assert counts(data) == {
        "World": 4,
        "Europe": 3,
        "France": 2,
        "Lyon": 2,
        "Spain": 1,
        "Asia": 1,
        "Japan": 1,
        "Deep": 1,
    }
    # Depth first, each node after its parent, and Deep on its own at the end.
    assert [row["label"] for row in data["results"]] == [
        "World",
        "Europe",
        "France",
        "Lyon",
        "Spain",
        "Asia",
        "Japan",
        "Deep",
    ]


def test_facets_follow_the_access_of_rows_and_nodes(catalog: Catalog) -> None:
    data = ok(client_as("staff").get("/api/products/facets/?taxonomy=region&rollup=true"))
    # Staff read the secret product, but nobody reads Hidden: Sunk counts for Deep only.
    assert counts(data)["France"] == 3 and counts(data)["Europe"] == 4
    assert "Hidden" not in counts(data) and counts(data)["Deep"] == 1


def test_facets_follow_the_list_filters_and_search(catalog: Catalog) -> None:
    url = f"/api/products/facets/?taxonomy=region&rollup=true&category={catalog.food.pk}"
    assert counts(ok(client_as(None).get(url))) == {
        "World": 2,
        "Europe": 2,
        "France": 1,
        "Lyon": 1,
        "Spain": 1,
    }
    url = "/api/products/facets/?taxonomy=category&search=saw"
    assert counts(ok(client_as(None).get(url))) == {"Tools": 1}


def test_facets_of_an_ordered_tree_and_of_an_adopted_field(catalog: Catalog) -> None:
    data = ok(client_as(None).get("/api/products/facets/?taxonomy=category&rollup=true"))
    assert counts(data) == {"Everything": 4, "Food": 3, "Fruit": 1, "Tools": 1}
    data = ok(client_as(None).get("/api/suppliers/facets/?rollup=true"))  # one taxonomy: no name
    assert data["taxonomy"] == "region"
    assert counts(data) == {"World": 2, "Europe": 1, "France": 1, "Asia": 1, "Japan": 1}


def test_facets_refuse_a_missing_or_unknown_taxonomy(catalog: Catalog) -> None:
    message = refused(client_as(None).get("/api/products/facets/"), "taxonomy")
    assert "region, category" in message
    refused(client_as(None).get("/api/products/facets/?taxonomy=colour"), "taxonomy")
    refused(client_as(None).get("/api/products/facets/?taxonomy=region&rollup=yes"), "rollup")


def test_facets_of_no_row_are_empty(catalog: Catalog) -> None:
    data = ok(client_as(None).get("/api/products/facets/?taxonomy=region&name=nothing"))
    assert data["results"] == []


def test_facets_take_the_same_queries_whatever_the_number_of_nodes(catalog: Catalog) -> None:
    client = client_as(None)
    url = "/api/products/facets/?taxonomy=region&rollup=true"
    with CaptureQueriesContext(connection) as few:
        ok(client.get(url))
    parent = catalog.lyon
    for index in range(40):
        parent = Region.objects.create(name=f"Street {index}", code=f"s{index}", parent=parent)
        Product.objects.create(name=f"Shop {index}").region.set([parent])
    with CaptureQueriesContext(connection) as many:
        data = ok(client.get(url))
    assert counts(data)["Lyon"] == 42 and counts(data)["Street 39"] == 1
    assert len(many) == len(few)
    facet_queries = [
        query["sql"] for query in many.captured_queries if "taxoapp_product_region" in query["sql"]
    ]
    assert len(facet_queries) == 2  # the counts, then the counted nodes


def test_facets_are_routed_only_for_a_model_with_taxonomies(catalog: Catalog) -> None:
    assert client_as(None).get("/api/regions/facets/").status_code == 404
    assert client_as(None).get(f"/api/products/{catalog.pie.pk}/tagged/").status_code == 404


# <key>/tagged/


def tagged(data: dict[str, Any]) -> dict[str, int]:
    return {f"{row['resource']}.{row['taxonomy']}": row["count"] for row in data["results"]}


def test_a_node_counts_its_rows_per_tagging_model(catalog: Catalog) -> None:
    data = ok(client_as(None).get(f"/api/regions/{catalog.france.pk}/tagged/"))
    assert data["descendants"] is False
    assert tagged(data) == {"products.region": 1, "suppliers.region": 1}
    row = data["results"][0]
    assert row["model"] == "taxoapp.product"


def test_a_node_counts_the_rows_under_it_with_descendants(catalog: Catalog) -> None:
    url = f"/api/regions/{catalog.europe.pk}/tagged/?descendants=true"
    assert tagged(ok(client_as(None).get(url))) == {"products.region": 3, "suppliers.region": 1}
    assert tagged(ok(client_as("staff").get(url))) == {"products.region": 4, "suppliers.region": 1}
    url = f"/api/categories/{catalog.everything.pk}/tagged/?descendants=true"
    assert tagged(ok(client_as(None).get(url))) == {"products.category": 4}


def test_tagged_follows_the_node_access(catalog: Catalog) -> None:
    assert client_as(None).get(f"/api/regions/{catalog.hidden.pk}/tagged/").status_code == 404
    url = f"/api/regions/{catalog.france.pk}/tagged/?descendants=2"
    refused(client_as(None).get(url), "descendants")


def test_tagged_takes_one_query_per_tagging_model(catalog: Catalog) -> None:
    client = client_as(None)
    url = f"/api/regions/{catalog.world.pk}/tagged/?descendants=true"
    with CaptureQueriesContext(connection) as few:
        ok(client.get(url))
    parent = catalog.japan
    for index in range(20):
        parent = Region.objects.create(name=f"Ward {index}", code=f"wd{index}", parent=parent)
    with CaptureQueriesContext(connection) as many:
        ok(client.get(url))
    assert len(many) == len(few)
    counted = [query["sql"] for query in many.captured_queries if "COUNT(" in query["sql"]]
    assert len(counted) == 2


# the OpenAPI document


@pytest.fixture
def schema() -> dict[str, Any]:
    from drf_spectacular.generators import SchemaGenerator

    generated: dict[str, Any] = SchemaGenerator().get_schema(request=None, public=True)
    return generated


def test_the_schema_documents_facets_and_tagged(schema: dict[str, Any]) -> None:
    paths = schema["paths"]
    facets = paths["/api/products/facets/"]["get"]
    params = {param["name"]: param for param in facets["parameters"]}
    assert sorted(params["taxonomy"]["schema"]["enum"]) == ["category", "region"]
    assert params["taxonomy"]["required"] is True
    assert "rollup" in params and "region" in params and "category_descendants" in params
    assert "ordering" not in params
    assert "/api/suppliers/facets/" in paths
    supplier = {p["name"]: p for p in paths["/api/suppliers/facets/"]["get"]["parameters"]}
    assert supplier["taxonomy"].get("required", False) is False
    assert "/api/regions/facets/" not in paths
    assert "/api/regions/{id}/tagged/" in paths and "/api/categories/{id}/tagged/" in paths
    assert "/api/products/{id}/tagged/" not in paths
    listed = {p["name"] for p in paths["/api/products/"]["get"]["parameters"]}
    assert {"region", "region_descendants", "category", "category_descendants"} <= listed
    component = schema["components"]["schemas"]["TaxoappProductFacets"]
    assert set(component["properties"]) == {"taxonomy", "rollup", "results"}
    product = schema["components"]["schemas"]["TaxoappProduct"]["properties"]
    assert product["region"]["x-karni-taxonomy"] == "region"
    assert product["region"]["x-karni-tree"] == {"parent": "parent", "ordered": False}
    supplier_fields = schema["components"]["schemas"]["TaxoappSupplier"]["properties"]
    assert supplier_fields["region"]["x-karni-taxonomy"] == "region"
