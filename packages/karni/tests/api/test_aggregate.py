"""``GET <resource>/aggregate/`` (karni.aggregation, experimental).

The catalog lives in :mod:`tests.aggregateapp`: ``Product`` declares its
aggregation in ``class Karni``. The suite runs on SQLite and PostgreSQL
(``TextNumber`` parses in SQL on both) and with ``KARNI_TEST_PK=bigint``.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from django.db.models import F
from django.test import override_settings
from django.utils import timezone

from karni.aggregation import (
    Aggregation,
    AggregationError,
    TextNumber,
    aggregation_of,
    parse_query,
    run_aggregate,
)
from karni.checks import check_aggregations
from karni.exceptions import KarniImproperlyConfigured
from karni.testing import client_as, user_with_roles
from karni.testing.performance import query_budget
from tests.aggregateapp.models import Category, Product

pytestmark = pytest.mark.django_db

URL = "/api/products/aggregate/"


@pytest.fixture(autouse=True)
def routes() -> Iterator[None]:
    with override_settings(
        ROOT_URLCONF="tests.aggregateapp.urls",
        KARNI_API_ROUTER="tests.aggregateapp.urls.get_router",
    ):
        yield


@pytest.fixture
def analyst() -> Any:
    """Reads every product (access) and the cost (``field_roles``: staff)."""
    return user_with_roles("analyst", "staff")


@pytest.fixture
def catalog(analyst: Any) -> dict[str, Any]:
    """Seven products across three categories (a tree), two channels and two years."""
    home = Category.objects.create(name="Home", code="home-1")
    lamps = Category.objects.create(name="Lamps", code="lamps-2", parent=home)
    chairs = Category.objects.create(name="Chairs", code="chairs-3", parent=home)
    toys = Category.objects.create(name="Toys")  # no code: the name labels it all the same
    rows = [
        ("Desk lamp", lamps, "online", True, dt.date(2024, 1, 10), "10.00", 3, "$1.2K", "4"),
        ("Floor lamp", lamps, "store", False, dt.date(2024, 5, 2), "30.00", 1, "450", "9"),
        ("Arm chair", chairs, "store", False, dt.date(2024, 11, 20), "120.00", 2, "1.5M", "60"),
        ("Stool", chairs, "online", True, dt.date(2025, 2, 1), "25.00", 5, "", "10"),
        ("Kite", toys, "online", False, dt.date(2025, 6, 30), "8.00", 10, "Undisclosed", "2"),
        ("Yo-yo", toys, "online", False, dt.date(2025, 7, 1), "2.00", 20, "2,000", "1"),
        ("Mystery box", None, "store", False, None, "5.00", 4, "1.2b", "1"),
    ]
    products = {}
    for name, category, channel, featured, launched, price, units, revenue, cost in rows:
        products[name] = Product.objects.create(
            name=name,
            category=category,
            channel=channel,
            featured=featured,
            launched_on=launched,
            listed_at=(
                timezone.make_aware(dt.datetime.combine(launched, dt.time(12, 0)))
                if launched
                else None
            ),
            price=Decimal(price),
            units=units,
            revenue_text=revenue,
            cost=Decimal(cost),
            owner=analyst,
        )
    return {"home": home, "lamps": lamps, "chairs": chairs, "toys": toys, **products}


def _get(client: Any, **params: Any) -> Any:
    return client.get(URL, params)


def _pairs(body: dict[str, Any], series: int = 0) -> dict[str, Any]:
    """``{category label: value}`` of one series."""
    values = body["series"][series]["values"]
    return {
        category["label"]: value for category, value in zip(body["categories"], values, strict=True)
    }


# the declaration


def test_the_model_declaration_is_read_and_checked() -> None:
    declared = aggregation_of(Product)
    assert declared is not None
    assert "category__parent" in declared.group_by
    assert declared.metrics == ("count", "sum", "avg", "min", "max", "distinct_count")
    assert declared.problems(Product) == []
    assert aggregation_of(Category) is None
    assert "launched_on:year" in declared.group_options(Product)
    assert "listed_at:month" in declared.group_options(Product)
    assert "listed_at:year" not in declared.group_options(Product)


def test_a_declaration_that_does_not_fit_is_e380() -> None:
    with pytest.raises(KarniImproperlyConfigured) as unknown_key:
        Aggregation.coerce({"group_by": ["channel"], "sums": ["price"]}, "Product.Karni.aggregate")
    assert unknown_key.value.code == "E380" and "'sums'" in unknown_key.value.message
    with pytest.raises(KarniImproperlyConfigured, match="median"):
        Aggregation(group_by=["channel"], metrics=["median"])
    with pytest.raises(KarniImproperlyConfigured, match="Django expression"):
        Aggregation(group_by=["channel"], expressions={"total": "price * units"})
    with pytest.raises(KarniImproperlyConfigured, match="list of names"):
        Aggregation(group_by="channel")
    broken = Aggregation(
        group_by=["colour", "price:year", "launched_on:week", "supplier_code", "category__nope"],
        values=["weight"],
    )
    problems = "\n".join(broken.problems(Product))
    assert "Product has no field 'colour'" in problems
    assert "a bucket needs a date" in problems
    assert "'week' is not a bucket" in problems
    assert "supplier_code is write-only" in problems
    assert "Category has no field 'nope'" in problems
    assert "values 'weight'" in problems
    assert Aggregation().problems(Product)[0].startswith("group_by is empty")


def test_karni_check_reports_e380_and_w570(monkeypatch: pytest.MonkeyPatch) -> None:
    assert [m for m in check_aggregations() if m.id.startswith("karni.")] == []
    monkeypatch.setattr(
        Product.Karni,
        "aggregate",
        {
            "group_by": ["colour"],
            "expressions": {"unused": TextNumber("revenue_text")},
        },
        raising=False,
    )
    ids = sorted(message.id for message in check_aggregations())
    assert ids == ["karni.E380", "karni.W570"]


# the request


def test_count_by_a_choice(catalog: dict[str, Any], analyst: Any) -> None:
    response = _get(client_as(user=analyst), group_by="channel")
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["group_by"] == "channel" and body["metric"] == "count"
    assert body["split"] is None and body["stacked"] is False and body["top"] is None
    assert body["categories"] == [
        {"key": "online", "label": "Online", "other": False},
        {"key": "store", "label": "Store", "other": False},
    ]
    assert body["series"] == [{"key": None, "label": "Count", "values": [4, 3]}]


def test_each_metric(catalog: dict[str, Any], analyst: Any) -> None:
    client = client_as(user=analyst)
    expected = {
        "sum": {"Online": 45.0, "Store": 155.0},
        "avg": {"Online": 11.25},
        "min": {"Online": 2.0, "Store": 5.0},
        "max": {"Online": 25.0, "Store": 120.0},
    }
    for metric, values in expected.items():
        body = _get(client, group_by="channel", metric=metric, value="price").json()
        assert body["metric"] == metric and body["value"] == "price"
        pairs = _pairs(body)
        for label, value in values.items():
            assert pairs[label] == pytest.approx(value), (metric, label)
    distinct = _get(client, group_by="channel", metric="distinct_count", value="category").json()
    assert _pairs(distinct) == {"Online": 3, "Store": 2}
    counted = _get(client, group_by="featured", metric="count", value="name").json()
    assert counted["series"][0]["label"] == "Count of name"
    labels = _get(client, group_by="channel", metric="avg", value="units").json()
    assert labels["series"][0]["label"] == "Average units"


def test_a_relation_groups_by_key_and_is_labelled_by_its_natural_key(
    catalog: dict[str, Any], analyst: Any
) -> None:
    body = _get(client_as(user=analyst), group_by="category", metric="sum", value="units").json()
    pairs = _pairs(body)
    assert pairs == {"Toys": 30, "Chairs": 7, "Lamps": 4, "(none)": 4}
    keys = {category["label"]: category["key"] for category in body["categories"]}
    assert keys["Lamps"] == str(catalog["lamps"].pk) or keys["Lamps"] == catalog["lamps"].pk
    assert keys["(none)"] is None


def test_a_relation_is_labelled_by_the_row_s_name_not_its_slug_key(
    catalog: dict[str, Any], analyst: Any
) -> None:
    """The natural key is a slug (``lamps-2``): the label is what people read, the key the id."""
    client = client_as(user=analyst)
    body = _get(client, group_by="category", stack="category__parent").json()
    labels = [category["label"] for category in body["categories"]]
    assert sorted(labels) == ["(none)", "Chairs", "Lamps", "Toys"]
    assert {series["label"] for series in body["series"]} == {"Home", "(none)"}
    lamps = next(c for c in body["categories"] if c["label"] == "Lamps")
    assert str(lamps["key"]) == str(catalog["lamps"].pk)  # the key still filters and links
    assert set(lamps) == {"key", "label", "other"}  # the same shape as before


def test_label_field_names_the_label_and_a_hidden_one_falls_back(
    catalog: dict[str, Any], analyst: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = client_as(user=analyst)
    monkeypatch.setattr(Category.Karni, "label_field", "code", raising=False)
    declared = _get(client, group_by="category").json()
    assert {c["label"] for c in declared["categories"]} >= {"lamps-2", "chairs-3"}
    monkeypatch.setattr(Category.Karni, "label_field", "name", raising=False)
    monkeypatch.setattr(Category.Karni, "field_roles", {"name": ["nobody"]}, raising=False)
    hidden = _get(client, group_by="category").json()
    assert "Lamps" not in {c["label"] for c in hidden["categories"]}
    assert "lamps-2" in {c["label"] for c in hidden["categories"]}  # the natural key


def test_a_label_field_the_model_lacks_is_e280(monkeypatch: pytest.MonkeyPatch) -> None:
    from django.apps import apps

    monkeypatch.setattr(Category.Karni, "label_field", "title", raising=False)
    found = [m.id for m in check_aggregations(apps.get_app_configs())]
    assert "karni.E280" in found


def test_a_relation_path(catalog: dict[str, Any], analyst: Any) -> None:
    client = client_as(user=analyst)
    parents = _get(client, group_by="category__parent").json()
    assert _pairs(parents) == {"(none)": 3, "Home": 4}
    names = _get(client, group_by="category__name").json()
    assert _pairs(names)["Lamps"] == 2


def test_a_boolean_and_a_number(catalog: dict[str, Any], analyst: Any) -> None:
    client = client_as(user=analyst)
    assert _pairs(_get(client, group_by="featured").json()) == {"No": 5, "Yes": 2}
    units = _get(client, group_by="units").json()
    assert {category["key"] for category in units["categories"]} == {1, 2, 3, 4, 5, 10, 20}


def test_each_date_bucket(catalog: dict[str, Any], analyst: Any) -> None:
    client = client_as(user=analyst)
    years = _get(client, group_by="launched_on:year").json()
    assert [c["key"] for c in years["categories"]] == ["2024", "2025", None]
    assert years["series"][0]["values"] == [3, 3, 1]
    quarters = _get(client, group_by="launched_on:quarter").json()
    assert [c["key"] for c in quarters["categories"]] == [
        "2024-Q1",
        "2024-Q2",
        "2024-Q4",
        "2025-Q1",
        "2025-Q2",
        "2025-Q3",
        None,
    ]
    assert quarters["categories"][0]["label"] == "Q1 2024"
    months = _get(client, group_by="launched_on:month", metric="sum", value="price").json()
    assert months["categories"][0] == {"key": "2024-01", "label": "Jan 2024", "other": False}
    assert months["series"][0]["values"][0] == pytest.approx(10.0)
    days = _get(client, group_by="launched_on").json()
    assert days["categories"][0]["key"] == "2024-01-10"
    listed = _get(client, group_by="listed_at:month").json()
    assert listed["categories"][0]["label"] == "Jan 2024"


def test_top_with_other(catalog: dict[str, Any], analyst: Any) -> None:
    body = _get(
        client_as(user=analyst), group_by="category", metric="sum", value="units", top=2
    ).json()
    assert body["top"] == 2
    assert [c["label"] for c in body["categories"]] == ["Toys", "Chairs", "Other"]
    assert body["categories"][-1] == {"key": None, "label": "Other", "other": True}
    # Other holds Lamps (4) and the product without a category (4).
    assert body["series"][0]["values"] == [30, 7, 8]
    averaged = _get(
        client_as(user=analyst), group_by="category", metric="avg", value="price", top=1
    ).json()
    assert [c["label"] for c in averaged["categories"]] == ["Chairs", "Other"]
    assert averaged["series"][0]["values"][1] == pytest.approx((10 + 30 + 8 + 2 + 5) / 5)
    everything = _get(client_as(user=analyst), group_by="channel", top=5).json()
    assert [c["label"] for c in everything["categories"]] == ["Online", "Store"]


def test_a_second_dimension_stacked_or_as_series(catalog: dict[str, Any], analyst: Any) -> None:
    client = client_as(user=analyst)
    stacked = _get(client, group_by="launched_on:year", stack="channel").json()
    assert stacked["split"] == "channel" and stacked["stacked"] is True
    assert [c["key"] for c in stacked["categories"]] == ["2024", "2025", None]
    assert [(s["key"], s["label"]) for s in stacked["series"]] == [
        ("online", "Online"),
        ("store", "Store"),
    ]
    assert stacked["series"][0]["values"] == [1, 3, 0]
    assert stacked["series"][1]["values"] == [2, 0, 1]
    series = _get(client, group_by="channel", series="featured", metric="max", value="price")
    body = series.json()
    assert body["stacked"] is False and body["split"] == "featured"
    assert [s["label"] for s in body["series"]] == ["No", "Yes"]
    # Ordered by value: Store (its highest price, 120) before Online (8 + 25).
    assert [c["label"] for c in body["categories"]] == ["Store", "Online"]
    no, yes = body["series"]
    assert yes["values"] == [None, pytest.approx(25.0)]  # no featured product in a store
    assert no["values"] == [pytest.approx(120.0), pytest.approx(8.0)]


def test_top_with_a_second_dimension(catalog: dict[str, Any], analyst: Any) -> None:
    body = _get(
        client_as(user=analyst),
        group_by="category",
        stack="channel",
        top=1,
        metric="sum",
        value="units",
    ).json()
    assert [c["label"] for c in body["categories"]] == ["Toys", "Other"]
    online, store = body["series"]
    assert online["values"] == [30, 8]  # Desk lamp 3 + Stool 5
    assert store["values"] == [0, 7]  # Floor lamp 1 + Arm chair 2 + Mystery box 4


def test_text_numbers_are_summed(catalog: dict[str, Any], analyst: Any) -> None:
    body = _get(client_as(user=analyst), group_by="channel", metric="sum", value="revenue").json()
    pairs = _pairs(body)
    # online: 1.2K + "" (none) + Undisclosed (none) + 2,000. store: 450 + 1.5M + 1.2b
    assert pairs["Online"] == pytest.approx(3200.0)
    assert pairs["Store"] == pytest.approx(450 + 1_500_000 + 1_200_000_000)
    counted = _get(
        client_as(user=analyst), group_by="channel", metric="count", value="revenue"
    ).json()
    assert _pairs(counted) == {"Online": 2, "Store": 3}


@pytest.mark.parametrize(
    ("text", "number"),
    [
        ("$1.2B", 1_200_000_000.0),
        ("450K", 450_000.0),
        (" $1,045,000 ", 1_045_000.0),
        ("9.5 million", 9_500_000.0),
        ("2.1bn", 2_100_000_000.0),
        ("€3MM", 3_000_000.0),
        ("-12.5", -12.5),
        ("7", 7.0),
        ("Undisclosed", None),
        ("", None),
        ("$25-30M", None),
        ("1.2.3", None),
    ],
)
def test_text_number_reads_in_sql(text: str, number: float | None) -> None:
    Product.objects.create(name="Row", revenue_text=text)
    found = Product.objects.annotate(read=TextNumber("revenue_text")).get().read
    assert found == (pytest.approx(number) if number is not None else None)


def test_a_text_number_of_your_own() -> None:
    Product.objects.create(name="Row", revenue_text="3 CR")
    crore = TextNumber("revenue_text", suffixes={"CR": 1e7, "L": 1e5})
    assert Product.objects.annotate(read=crore).get().read == pytest.approx(3e7)
    plain = TextNumber(F("revenue_text"), strip=())
    assert Product.objects.annotate(read=plain).get().read is None  # the space stays


# filters and access


def test_list_filters_and_search_apply(catalog: dict[str, Any], analyst: Any) -> None:
    client = client_as(user=analyst)
    filtered = _get(client, group_by="channel", featured="true").json()
    assert _pairs(filtered) == {"Online": 2}
    searched = _get(client, group_by="channel", search="lamp").json()
    assert _pairs(searched) == {"Online": 1, "Store": 1}
    ranged = _get(client, group_by="channel", price__gte="25").json()
    assert _pairs(ranged) == {"Store": 2, "Online": 1}
    refused = _get(client, group_by="channel", price__gte="lots")
    assert refused.status_code == 400


def test_a_user_sees_only_the_rows_the_list_shows(catalog: dict[str, Any]) -> None:
    owner = user_with_roles()
    Product.objects.filter(name__in=["Kite", "Arm chair"]).update(owner=owner)
    client = client_as(user=owner)
    listed = client.get("/api/products/").json()
    assert listed["count"] == 2
    body = _get(client, group_by="channel").json()
    assert _pairs(body) == {"Online": 1, "Store": 1}
    assert sum(body["series"][0]["values"]) == listed["count"]
    stranger = client_as(user=user_with_roles())
    assert _get(stranger, group_by="channel").json()["categories"] == []
    assert _get(client_as(None), group_by="channel").status_code in (401, 403)


def test_a_field_hidden_from_the_requester_is_refused(
    catalog: dict[str, Any], analyst: Any
) -> None:
    owner = user_with_roles()
    Product.objects.update(owner=owner)
    client = client_as(user=owner)
    for params in (
        {"group_by": "cost"},
        {"group_by": "channel", "metric": "sum", "value": "cost"},
        {"group_by": "channel", "stack": "cost"},
    ):
        response = _get(client, **params)
        assert response.status_code == 400, params
        assert "hidden" in response.json()["detail"]
    assert _get(client_as(user=analyst), group_by="cost").status_code == 200


# refusals


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({}, "E382"),
        ({"group_by": "name"}, "E382"),
        ({"group_by": "supplier_code"}, "E382"),
        ({"group_by": "owner"}, "E382"),
        ({"group_by": "channel", "metric": "median"}, "E383"),
        ({"group_by": "channel", "metric": "sum"}, "E384"),
        ({"group_by": "channel", "metric": "sum", "value": "featured"}, "E384"),
        ({"group_by": "channel", "metric": "sum", "value": "name"}, "E384"),
        ({"group_by": "channel", "metric": "sum", "value": "supplier_code"}, "E384"),
        ({"group_by": "channel:year"}, "E385"),
        ({"group_by": "launched_on:week"}, "E385"),
        ({"group_by": "listed_at:year"}, "E382"),
        ({"group_by": "channel", "top": "0"}, "E386"),
        ({"group_by": "channel", "top": "many"}, "E386"),
        ({"group_by": "channel", "stack": "featured", "series": "featured"}, "E386"),
        ({"group_by": "channel", "stack": "channel"}, "E386"),
        ({"group_by": "channel", "stack": "name"}, "E382"),
    ],
)
def test_undeclared_and_invalid_requests_are_400_with_a_code(
    catalog: dict[str, Any], analyst: Any, params: dict[str, str], code: str
) -> None:
    response = _get(client_as(user=analyst), **params)
    assert response.status_code == 400, response.content
    assert response.json()["code"] == code


def test_too_many_groups_is_e387(catalog: dict[str, Any], analyst: Any) -> None:
    with override_settings(KARNI_AGGREGATE_MAX_GROUPS=3):
        response = _get(client_as(user=analyst), group_by="units")
        assert response.status_code == 400
        assert response.json()["code"] == "E387"
        topped = _get(client_as(user=analyst), group_by="units", top=3)
        assert topped.status_code == 200
        assert len(topped.json()["categories"]) == 4


def test_a_resource_without_a_declaration_answers_404(analyst: Any) -> None:
    response = client_as(user=analyst).get("/api/categories/aggregate/", {"group_by": "name"})
    assert response.status_code == 404
    assert response.json()["code"] == "E381"


def test_the_viewset_declaration_wins(catalog: dict[str, Any], analyst: Any) -> None:
    client = client_as(user=analyst)
    url = "/api/narrow-products/aggregate/"
    assert client.get(url, {"group_by": "channel"}).status_code == 200
    assert client.get(url, {"group_by": "category"}).json()["code"] == "E382"
    refused = client.get(url, {"group_by": "channel", "metric": "sum", "value": "price"})
    assert refused.json()["code"] == "E383"


# queries


def test_one_query_or_two_with_other(catalog: dict[str, Any], analyst: Any) -> None:
    category = Category.objects.first()
    assert category is not None
    queryset = Product.objects.all()
    declared = aggregation_of(Product)
    assert declared is not None
    plain = parse_query(declared, Product, {"group_by": "category"}, user=analyst)
    with query_budget(1):
        run_aggregate(queryset, plain)
    stacked = parse_query(
        declared, Product, {"group_by": "launched_on:year", "stack": "channel"}, user=analyst
    )
    with query_budget(1):
        run_aggregate(queryset, stacked)
    topped = parse_query(
        declared, Product, {"group_by": "category", "top": "2", "stack": "channel"}, user=analyst
    )
    with query_budget(2):
        run_aggregate(queryset, topped)
    topped_flat = parse_query(declared, Product, {"group_by": "category", "top": "1"}, user=analyst)
    with query_budget(2):
        run_aggregate(queryset, topped_flat)


def test_the_query_count_does_not_grow_with_rows(catalog: dict[str, Any], analyst: Any) -> None:
    client = client_as(user=analyst)
    _get(client, group_by="category", top=2, stack="channel")  # warm-up: the requester's roles
    small = _get(client, group_by="category", top=2, stack="channel")
    for index in range(30):
        Product.objects.create(
            name=f"Extra {index}", category=catalog["toys"], channel="store", owner=analyst
        )
    large = _get(client, group_by="category", top=2, stack="channel")
    assert small.status_code == large.status_code == 200
    assert small["X-Karni-Queries"] == large["X-Karni-Queries"]


def test_a_parsed_request_names_the_rows_it_will_read(analyst: Any) -> None:
    declared = aggregation_of(Product)
    assert declared is not None
    with pytest.raises(AggregationError) as refused:
        parse_query(declared, Product, {"group_by": "channel", "metric": "sum"}, user=analyst)
    assert refused.value.code == "E384"
    query = parse_query(
        declared, Product, {"group_by": "launched_on:year", "series": "channel"}, user=analyst
    )
    assert query.group_by.bucket == "year" and query.split is not None
    assert query.stacked is False


# the OpenAPI document


def _schema() -> tuple[dict[str, Any], list[str]]:
    from drf_spectacular.drainage import GENERATOR_STATS
    from drf_spectacular.generators import SchemaGenerator

    GENERATOR_STATS.reset()
    with GENERATOR_STATS.silence():
        schema = SchemaGenerator().get_schema(request=None, public=True)
    messages = [*GENERATOR_STATS._warn_cache, *GENERATOR_STATS._error_cache]
    GENERATOR_STATS.reset()
    return schema, messages


def test_the_schema_documents_the_action_its_parameters_and_its_response() -> None:
    schema, messages = _schema()
    assert not [m for m in messages if "aggregate" in m.lower()], messages
    operation = schema["paths"]["/api/products/aggregate/"]["get"]
    declared = aggregation_of(Product)
    assert declared is not None
    assert operation["x-karni-aggregate"]["metrics"] == list(declared.metrics)
    assert "launched_on:quarter" in operation["x-karni-aggregate"]["group_by"]
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert parameters["group_by"]["required"] is True
    assert "category__parent" in parameters["group_by"]["schema"]["enum"]
    assert set(parameters["metric"]["schema"]["enum"]) == set(declared.metrics)
    assert set(parameters["value"]["schema"]["enum"]) == set(declared.values)
    assert parameters["top"]["schema"]["type"] == "integer"
    assert {"stack", "series", "search", "channel", "price__gte"} <= set(parameters)
    assert "ordering" not in parameters and "page" not in parameters
    response = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert response == {"$ref": "#/components/schemas/AggregateResult"}
    result = schema["components"]["schemas"]["AggregateResult"]
    assert set(result["properties"]) == {
        "group_by",
        "metric",
        "value",
        "split",
        "stacked",
        "top",
        "categories",
        "series",
    }
    assert operation["x-karni-access"] == {"any": [{"owned": "owner"}, {"role": ["analyst"]}]}
    narrow = schema["paths"]["/api/narrow-products/aggregate/"]["get"]
    assert narrow["x-karni-aggregate"] == {
        "group_by": ["channel"],
        "values": [],
        "metrics": ["count"],
    }
    assert "/api/categories/aggregate/" not in schema["paths"]
