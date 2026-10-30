"""The Chart model: its query string and the checks a save runs (experimental)."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from karni_charts.models import Chart
from karni_charts.services import ChartError, check_chart, source_viewset, sources

pytestmark = pytest.mark.django_db


def _chart(**fields: object) -> Chart:
    values: dict[str, object] = {
        "name": "Products by channel",
        "slug": "products-by-channel",
        "source": "products",
        "x_field": "channel",
    }
    values.update(fields)
    return Chart(**values)


def test_the_query_string_follows_the_axes() -> None:
    assert _chart().query() == {"group_by": "channel", "metric": "count"}
    chart = _chart(
        x_field="launched_on",
        x_bucket="quarter",
        y_metric="sum",
        y_value="revenue",
        z_field="category",
        z_mode="series",
        top=3,
    )
    assert chart.query() == {
        "group_by": "launched_on:quarter",
        "metric": "sum",
        "value": "revenue",
        "top": "3",
        "series": "category",
    }
    stacked = _chart(z_field="launched_on", z_bucket="year")
    assert stacked.query()["stack"] == "launched_on:year"


def test_the_sources_are_the_resources_that_declare_an_aggregation() -> None:
    assert set(sources()) == {"products"}
    assert source_viewset("products").__name__ == "ProductViewSet"
    with pytest.raises(ChartError) as missing:
        source_viewset("notes")
    assert missing.value.code == "CHART001" and "products" in missing.value.message


def test_a_valid_chart_saves() -> None:
    chart = _chart(y_metric="avg", y_value="price", z_field="launched_on", z_bucket="year")
    chart.full_clean()
    chart.save()
    assert Chart.objects.get(slug="products-by-channel").z_bucket == "year"
    assert str(chart) == "Products by channel"


@pytest.mark.parametrize(
    ("fields", "code", "field"),
    [
        ({"source": "notes"}, "CHART001", "source"),
        ({"x_field": "name"}, "CHART004", "x_field"),
        ({"y_metric": "sum"}, "CHART004", "x_field"),
        ({"y_metric": "sum", "y_value": "name"}, "CHART004", "x_field"),
        ({"x_field": "channel", "x_bucket": "year"}, "CHART004", "x_field"),
        ({"z_field": "channel"}, "CHART004", "x_field"),
        ({"default_filters": ["channel"]}, "CHART003", "default_filters"),
        ({"default_filters": {"channel": {"in": "online"}}}, "CHART003", "default_filters"),
        ({"allowed_filters": "channel"}, "CHART003", "default_filters"),
        ({"allowed_filters": ["group_by"]}, "CHART003", "default_filters"),
        ({"default_filters": {"top": 3}}, "CHART003", "default_filters"),
    ],
)
def test_a_chart_that_cannot_run_is_refused(
    fields: dict[str, object], code: str, field: str
) -> None:
    chart = _chart(**fields)
    with pytest.raises(ValidationError) as refused:
        chart.full_clean()
    assert code in str(refused.value.message_dict[field])
    with pytest.raises(ChartError) as direct:
        check_chart(chart)
    assert direct.value.code == code


def test_the_checks_name_the_source_refusal() -> None:
    with pytest.raises(ChartError) as refused:
        check_chart(_chart(x_field="name"))
    assert "E382" in refused.value.message
