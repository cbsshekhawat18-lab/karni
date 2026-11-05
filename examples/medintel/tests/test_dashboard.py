"""The trials dashboard and the saved deal charts: aggregates under the same grants as the lists."""

from collections import Counter, defaultdict

import pytest
from django.db.models import Q

from intel.models import Condition, Deal, Intervention, Trial

pytestmark = pytest.mark.django_db


def series(response) -> dict[str, float]:
    """An aggregate answer as {category label: value} (one series)."""
    body = response.json()
    assert response.status_code == 200, body
    (only,) = body["series"]
    return {category["label"]: value for category, value in zip(body["categories"], only["values"], strict=True)}


def test_trials_by_phase_status_and_year_match_the_rows(client_for):
    client = client_for("demo@example.com")
    for group, label in (("phase", lambda v: Trial.Phase(v).label), ("status", lambda v: Trial.Status(v).label), ("start_year", str)):
        counts = Counter(Trial.objects.values_list(group, flat=True))
        got = series(client.get("/api/trials/aggregate/", {"group_by": group}))
        assert got == {label(key): count for key, count in counts.items()}
    assert sum(got.values()) == 300


def test_enrollment_summed_per_year(client_for):
    expected: dict[str, int] = defaultdict(int)
    for year, enrollment in Trial.objects.values_list("start_year", "enrollment"):
        expected[str(year)] += enrollment
    got = series(client_for("demo@example.com").get("/api/trials/aggregate/", {"group_by": "start_year", "metric": "sum", "value": "enrollment"}))
    assert got == expected


def test_a_second_dimension_stacks_the_bars(client_for):
    body = client_for("demo@example.com").get("/api/trials/aggregate/", {"group_by": "start_year", "stack": "phase"}).json()
    assert body["stacked"] and {s["label"] for s in body["series"]} == {"Phase 1", "Phase 2", "Phase 3", "Phase 4"}
    assert sum(sum(s["values"]) for s in body["series"]) == 300


def test_a_customers_aggregate_counts_only_their_rows(client_for):
    oncology = Condition.objects.subtree_ids([Condition.objects.get(name="Oncology").pk])
    visible = Trial.objects.filter(conditions__in=oncology).distinct()
    got = series(client_for("oncology@example.com").get("/api/trials/aggregate/", {"group_by": "status"}))
    assert got == {Trial.Status(key).label: n for key, n in Counter(visible.values_list("status", flat=True)).items()}


def test_an_aggregate_over_a_field_that_is_not_declared_is_refused(client_for):
    assert client_for("demo@example.com").get("/api/trials/aggregate/", {"group_by": "title"}).status_code == 400


def test_the_saved_chart_reads_deal_value_by_year(client_for):
    expected: dict[str, float] = defaultdict(float)
    for year, value in Deal.objects.values_list("year", "value"):
        expected[str(year)] += float(value)
    response = client_for("demo@example.com").get("/api/charts/deal-value-by-year/data/")
    assert response.status_code == 200
    assert {k: round(v, 2) for k, v in series_of(response).items()} == {k: round(v, 2) for k, v in expected.items()}


def series_of(response) -> dict[str, float]:
    data = response.json()["data"]
    return {c["label"]: v for c, v in zip(data["categories"], data["series"][0]["values"], strict=True)}


def test_the_saved_chart_follows_the_viewers_grants(client_for):
    vaccines = Intervention.objects.subtree_ids([Intervention.objects.get(name="Vaccines").pk])
    counts = Counter(Deal.objects.filter(interventions__in=vaccines).distinct().values_list("year", flat=True))
    response = client_for("vaccines@example.com").get("/api/charts/deals-by-year/data/")
    assert series_of(response) == {str(year): n for year, n in counts.items()}
    assert client_for("oncology@example.com").get("/api/charts/deals-by-year/data/").status_code == 403


def test_a_saved_chart_takes_only_the_filters_it_allows(client_for):
    client = client_for("demo@example.com")
    node = Intervention.objects.get(name="Biologics")
    filters = {"interventions": str(node.pk), "interventions_descendants": "true"}
    narrowed = series_of(client.get("/api/charts/deals-by-year/data/", filters))
    expected = Counter(Deal.objects.filter(Q(interventions__in=Intervention.objects.subtree_ids([node.pk]))).distinct().values_list("year", flat=True))
    assert narrowed == {str(year): n for year, n in expected.items()}
    refused = client.get("/api/charts/deals-by-year/data/", {"year": "2020"})
    assert refused.status_code == 400 and refused.json()["code"] == "CHART002"
