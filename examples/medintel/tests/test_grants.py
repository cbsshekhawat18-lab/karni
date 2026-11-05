"""Grant-limited views: a customer sees only the rows under the nodes granted to them."""

import pytest
from django.db.models import Q

from intel.models import Brand, Company, Condition, Deal, Intervention, Person, Trial

pytestmark = pytest.mark.django_db

ANALYST, ONCOLOGY, VACCINES = "analyst@example.com", "oncology@example.com", "vaccines@example.com"


def under(tree, name: str) -> set:
    return tree.objects.subtree_ids([tree.objects.get(name=name).pk])


def ids(client, resource: str, **params) -> set[str]:
    """Every id the list shows, page after page (the page size is capped at 100)."""
    found: set[str] = set()
    response = client.get(f"/api/{resource}/", {"page_size": 100, **params})
    while True:
        assert response.status_code == 200, response.content
        found |= {row["id"] for row in response.json()["results"]}
        if not response.json()["next"]:
            return found
        response = client.get(response.json()["next"])


def pks(queryset) -> set[str]:
    return {str(pk) for pk in queryset.values_list("pk", flat=True)}


def test_the_seed_is_large_enough_to_mean_something():
    assert Condition.objects.count() == 90 and Intervention.objects.count() == 35
    depth = max(len(list(Condition.objects.ancestors(node))) for node in Condition.objects.filter(children=None))
    assert depth >= 3 and Trial.objects.count() == 300 and Deal.objects.count() == 120


def test_a_condition_grant_shows_the_trials_under_that_node(client_for):
    expected = Trial.objects.filter(conditions__in=under(Condition, "Oncology")).distinct()
    assert 0 < expected.count() < Trial.objects.count()
    assert ids(client_for(ONCOLOGY), "trials") == pks(expected)


def test_an_intervention_grant_shows_the_rows_tagged_under_that_node(client_for):
    node = under(Intervention, "Vaccines")
    client = client_for(VACCINES)
    assert ids(client, "trials") == pks(Trial.objects.filter(interventions__in=node).distinct())
    assert ids(client, "companies") == pks(Company.objects.filter(interventions__in=node).distinct())
    assert ids(client, "brands") == pks(Brand.objects.filter(interventions__in=node).distinct())
    assert ids(client, "deals") == pks(Deal.objects.filter(interventions__in=node).distinct())
    assert ids(client, "persons") == pks(Person.objects.filter(company__interventions__in=node).distinct())


def test_two_grants_of_one_user_are_a_union(client_for):
    oncology, biologics = under(Condition, "Oncology"), under(Intervention, "Biologics")
    expected = Trial.objects.filter(Q(conditions__in=oncology) | Q(interventions__in=biologics)).distinct()
    assert ids(client_for(ANALYST), "trials") == pks(expected)


def test_a_model_without_a_grant_is_closed(client_for):
    client = client_for(ONCOLOGY)
    for resource in ("companies", "deals", "brands", "persons"):
        assert client.get(f"/api/{resource}/").status_code == 403


def test_staff_sees_every_row(client_for):
    assert len(ids(client_for("demo@example.com"), "trials")) == 300


def search(client, q: str) -> dict[str, set[str]]:
    groups = client.get("/api/search/", {"q": q, "limit": 50}).json()["groups"]
    return {group["resource"]: {hit["id"] for hit in group["hits"]} for group in groups}


def test_search_returns_only_visible_rows(client_for):
    client = client_for(VACCINES)
    found = search(client, "Veltra")
    assert {"trials", "brands"} <= set(found)
    for resource, hits in found.items():
        assert hits <= ids(client, resource)
    assert search(client_for("demo@example.com"), "Veltra")["trials"] - ids(client, "trials")  # staff finds more


def test_search_skips_a_model_the_user_may_not_read(client_for):
    found = search(client_for(ONCOLOGY), "Veltra")
    assert "trials" in found and set(found).isdisjoint({"companies", "deals", "brands", "persons"})


def test_the_cache_never_mixes_two_users_scopes(client_for):
    one, two = client_for(ONCOLOGY), client_for(VACCINES)
    first = [one.get("/api/trials/", {"page_size": 1}).json()["count"] for _ in range(2)]
    other = [two.get("/api/trials/", {"page_size": 1}).json()["count"] for _ in range(2)]
    assert first[0] == first[1] != other[0] == other[1]
    assert one.get("/api/trials/", {"page_size": 1}).headers["X-Cache"] in {"HIT", "MISS", "BYPASS"}


def test_facets_count_only_visible_rows(client_for):
    response = client_for(ONCOLOGY).get("/api/trials/facets/", {"taxonomy": "conditions", "rollup": "true"})
    assert response.status_code == 200
    root = next(node for node in response.json()["results"] if node["label"] == "Oncology")
    assert root["count"] == Trial.objects.filter(conditions__in=under(Condition, "Oncology")).distinct().count()


def test_the_access_forest_marks_the_granted_node(client_for):
    response = client_for(ONCOLOGY).get("/api/conditions/access/", {"permission": "intel.trial:view"})
    granted = [node["label"] for node in response.json()["results"] if node["granted"]]
    assert granted == ["Oncology"]


def test_the_menu_follows_the_grants(client_for):
    def labels(email: str) -> set[str]:
        items = client_for(email).get("/api/navigation/").json()["items"]
        return {child["label"] for item in items for child in item.get("children") or [item]}

    assert {"Players", "Deals chart"} <= labels(VACCINES)
    assert {"Trials", "Trials dashboard"} <= labels(ONCOLOGY)
    assert not {"Companies", "Players", "Deals chart"} & labels(ONCOLOGY)
