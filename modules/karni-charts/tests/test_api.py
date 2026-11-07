"""The charts API: definitions, and each chart's data under its source's access."""

from __future__ import annotations

from typing import Any

import pytest
from django.test import override_settings
from karni.testing import client_as, user_with_roles

from karni_charts.models import Chart

pytestmark = pytest.mark.django_db


def _values(body: dict[str, Any]) -> dict[str, list[Any]]:
    """``{series label: values}`` of an aggregate."""
    return {entry["label"]: entry["values"] for entry in body["series"]}


def test_the_definitions_are_read_only(chart: Chart, analyst: Any) -> None:
    client = client_as(user=analyst)
    listed = client.get("/api/charts/").json()
    assert [row["slug"] for row in listed["results"]] == ["launches-per-year"]
    one = client.get("/api/charts/launches-per-year/").json()
    assert one["x_field"] == "launched_on" and one["z_mode"] == "stack"
    assert client.post("/api/charts/", {"name": "x"}).status_code == 403  # access first
    staff = client_as(user=user_with_roles("staff"))
    assert staff.post("/api/charts/", {"name": "x"}).status_code == 405  # the admin writes
    assert staff.delete("/api/charts/launches-per-year/").status_code == 405
    assert client_as(None).get("/api/charts/").status_code in (401, 403)


def test_the_data_comes_from_the_source_aggregate(
    chart: Chart, catalog: dict[str, Any], analyst: Any
) -> None:
    response = client_as(user=analyst).get("/api/charts/launches-per-year/data/")
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["chart"]["slug"] == "launches-per-year"
    data = body["data"]
    assert data["group_by"] == "launched_on:year" and data["stacked"] is True
    assert [c["key"] for c in data["categories"]] == ["2024", "2025"]
    assert _values(data) == {"Online": [1, 2], "Store": [1, 1]}


def test_a_viewer_sees_only_the_rows_the_source_shows_them(
    chart: Chart, catalog: dict[str, Any], owner: Any
) -> None:
    """The owner reads two products in the list, so the chart counts two."""
    client = client_as(user=owner)
    assert client.get("/api/products/").json()["count"] == 2
    data = client.get("/api/charts/launches-per-year/data/").json()["data"]
    assert _values(data) == {"Online": [1, 1]}
    stranger = client_as(user=user_with_roles("user"))
    assert stranger.get("/api/charts/launches-per-year/data/").json()["data"]["categories"] == []


def test_allowed_filters_narrow_it_and_others_are_refused(
    chart: Chart, catalog: dict[str, Any], analyst: Any
) -> None:
    client = client_as(user=analyst)
    online = client.get("/api/charts/launches-per-year/data/", {"channel": "online"}).json()
    assert _values(online["data"]) == {"Online": [1, 2]}
    later = client.get("/api/charts/launches-per-year/data/", {"launched_on__gte": "2025-01-01"})
    assert [c["key"] for c in later.json()["data"]["categories"]] == ["2025"]
    refused = client.get("/api/charts/launches-per-year/data/", {"price__gte": "5"})
    assert refused.status_code == 400 and refused.json()["code"] == "CHART002"
    axes = client.get("/api/charts/launches-per-year/data/", {"group_by": "channel"})
    assert axes.json()["code"] == "CHART002"


def test_default_filters_always_apply(catalog: dict[str, Any], analyst: Any) -> None:
    Chart.objects.create(
        name="Store revenue by category",
        slug="store-revenue",
        source="products",
        x_field="category",
        y_metric="sum",
        y_value="revenue",
        default_filters={"channel": "store"},
    )
    data = client_as(user=analyst).get("/api/charts/store-revenue/data/").json()["data"]
    labels = [c["label"] for c in data["categories"]]
    assert labels == ["Toys", "Lamps"]
    assert data["series"][0]["values"] == [pytest.approx(1_500_000.0), pytest.approx(450.0)]


def test_the_source_refusal_is_passed_on(catalog: dict[str, Any], analyst: Any) -> None:
    """A chart saved before the source changed answers what the source answers."""
    Chart.objects.create(name="Broken", slug="broken", source="products", x_field="name")
    response = client_as(user=analyst).get("/api/charts/broken/data/")
    assert response.status_code == 400 and response.json()["code"] == "E382"
    Chart.objects.create(name="Gone", slug="gone", source="notes", x_field="text")
    gone = client_as(user=analyst).get("/api/charts/gone/data/")
    assert gone.status_code == 400 and gone.json()["code"] == "CHART001"


def test_karni_charts_read_chooses_who_reads_the_definitions(chart: Chart) -> None:
    with override_settings(KARNI_CHARTS_READ="public"):
        assert client_as(None).get("/api/charts/").status_code == 200
        # The data still follows the source: anonymous callers may not list products.
        assert client_as(None).get("/api/charts/launches-per-year/data/").status_code in (401, 403)
    with override_settings(KARNI_CHARTS_READ="granted"):
        assert client_as(user=user_with_roles("analyst")).get("/api/charts/").status_code == 200
        nobody = client_as(user=user_with_roles())
        assert nobody.get("/api/charts/").status_code == 403


def test_the_schema_documents_the_data_action(chart: Chart) -> None:
    from drf_spectacular.generators import SchemaGenerator

    schema = SchemaGenerator().get_schema(request=None, public=True)
    assert "/api/charts/{slug}/data/" in schema["paths"]
    assert "post" not in schema["paths"]["/api/charts/"]
    assert "/api/products/aggregate/" in schema["paths"]


@pytest.mark.parametrize("name", ["kind", "name", "slug", "source", "position"])
def test_a_viewer_filter_named_like_a_chart_field_is_not_a_chart_lookup(
    chart: Chart, catalog: dict[str, Any], analyst: Any, name: str
) -> None:
    """The chart's own list filters must not narrow the lookup of the chart (CHART002, not 404)."""
    response = client_as(user=analyst).get("/api/charts/launches-per-year/data/", {name: "x"})
    assert response.status_code == 400 and response.json()["code"] == "CHART002"
