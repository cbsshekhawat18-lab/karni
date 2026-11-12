"""The people API: who sees what, the signed-in person, facts, merge, erase, query counts."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from karni.accounts.permissions import assign_role
from karni.people.models import Address, Membership, Organisation, Person
from karni.testing import client_as
from tests.helpdeskapp.models import Ticket
from tests.loyaltyapp.models import Visit
from tests.people.conftest import make_user

pytestmark = pytest.mark.django_db


_COUNT = iter(range(1, 10_000))


def _client(*roles: str, email: str = "", verified: bool = True) -> Any:
    address = email or f"{'-'.join(roles) or 'nobody'}{next(_COUNT)}@example.net"
    user = make_user(address, verified=verified)
    for role in roles:
        assign_role(user, role)
    return client_as(user=user)


def _ids(response: Any) -> set[str]:
    return {row["id"] for row in response.data["results"]}


# who sees what


def test_people_answer_the_roles_granted_on_them(family: dict[str, Any]) -> None:
    everyone = {str(family["keep"].pk), str(family["drop"].pk)}
    assert _ids(_client("viewer").get("/api/people/")) == everyone
    assert _client("viewer").post("/api/people/", {"email": "a@example.com"}).status_code == 403
    assert client_as(None).get("/api/people/").status_code == 401
    assert _client().get("/api/people/").status_code == 403  # no grant at all


def test_a_customer_reaches_their_own_person_only(family: dict[str, Any]) -> None:
    client = _client("customer", email="ana@example.com")  # links Ana's record on creation
    assert _ids(client.get("/api/people/")) == {str(family["keep"].pk)}
    other = client.get(f"/api/people/{family['drop'].pk}/")
    assert other.status_code == 404
    found = client.get("/api/search/", {"q": "Ana"}).data["groups"]
    hits = [hit["id"] for group in found for hit in group["hits"] if group["resource"] == "people"]
    assert hits == [str(family["keep"].pk)]


def test_the_signed_in_person(family: dict[str, Any]) -> None:
    client = _client(email="ana@example.com")
    me = client.get("/api/people/me/")
    assert me.status_code == 200 and me.data["id"] == str(family["keep"].pk)
    changed = client.patch(
        "/api/people/me/",
        {"given_name": "Ana Maria", "email": "taken@example.com", "time_zone": "Europe/Lisbon"},
        format="json",
    )
    assert changed.status_code == 200, changed.data
    family["keep"].refresh_from_db()
    assert family["keep"].given_name == "Ana Maria"
    assert family["keep"].email == "ana@example.com"  # read only here: it follows the account
    bad = client.patch("/api/people/me/", {"time_zone": "Moon/Base"}, format="json")
    assert bad.status_code == 400 and "E256" in str(bad.data)
    assert (
        _client(email="new@example.com", verified=False).get("/api/people/me/").status_code == 404
    )
    created = _client(email="fresh@example.com").get("/api/people/me/")
    assert created.status_code == 200 and created.data["email"] == "fresh@example.com"


def test_the_email_rules_answer_400(family: dict[str, Any]) -> None:
    admin = _client("admin")
    taken = admin.post("/api/people/", {"email": "ANA@example.com"}, format="json")
    assert taken.status_code == 400 and "E254" in str(taken.data)
    created = admin.post("/api/people/", {"given_name": "Dev", "email": "dev@example.com"})
    assert created.status_code == 201 and created.data["user"] is None  # never stamped
    user = make_user("ana@example.com")
    family["keep"].refresh_from_db()
    assert family["keep"].user_id == user.pk
    linked = admin.patch(
        f"/api/people/{family['keep'].pk}/", {"email": "else@example.com"}, format="json"
    )
    assert linked.status_code == 400 and "E255" in str(linked.data)
    assert (
        (
            admin.patch(
                f"/api/people/{family['keep'].pk}/", {"user": None, "phone": "+1"}, format="json"
            ).data["user"]
        )
        == user.pk
    )


# facts


def test_facts_show_filter_and_order_in_the_list(family: dict[str, Any]) -> None:
    client = _client("viewer")
    response = client.get("/api/people/", {"facts": "visits,open_tickets", "ordering": "-visits"})
    rows = response.data["results"]
    assert [row["id"] for row in rows] == [str(family["keep"].pk), str(family["drop"].pk)]
    assert rows[0]["facts"] == {"visits": 2, "open_tickets": 1}
    regulars = client.get("/api/people/", {"visits__gte": 2})
    assert _ids(regulars) == {str(family["keep"].pk)}
    assert "facts" not in regulars.data["results"][0]
    every = client.get(f"/api/people/{family['drop'].pk}/", {"facts": "all"}).data["facts"]
    assert every["last_visit"] == "2026-11-03"
    assert Decimal(every["loyalty_spent"]) == Decimal("30")
    unknown = client.get("/api/people/", {"facts": "lifetime_value"})
    assert unknown.status_code == 400 and "E257" in str(unknown.data)
    assert client.get("/api/people/", {"visits__in": "1"}).status_code == 400
    listed = client.get("/api/people/facts/").data
    assert {"name": "visits", "label": "Visits", "kind": "count"}.items() <= listed[0].items()


def test_the_list_costs_the_same_queries_for_more_people(family: dict[str, Any]) -> None:
    client = _client("viewer")
    params = {"facts": "all", "ordering": "-loyalty_spent"}
    client.get("/api/people/", params)  # warm the role and content type caches

    def cost() -> int:
        with CaptureQueriesContext(connection) as queries:
            assert client.get("/api/people/", params).status_code == 200
        return len(queries)

    few = cost()
    for index in range(12):
        person = Person.objects.create(email=f"member{index}@example.com")
        Visit.objects.create(person=person, visited_on=dt.date(2026, 11, 1))
        Ticket.objects.create(person=person, subject="Question")
    assert cost() == few


@pytest.mark.parametrize("path", ["organisations", "people-memberships", "people-addresses"])
def test_the_other_lists_cost_the_same_for_more_rows(family: dict[str, Any], path: str) -> None:
    client = _client("admin")
    client.get(f"/api/{path}/")

    def cost() -> int:
        with CaptureQueriesContext(connection) as queries:
            assert client.get(f"/api/{path}/").status_code == 200
        return len(queries)

    few = cost()
    for index in range(10):
        org = Organisation.objects.create(name=f"Pebble Creek {index}")
        person = Person.objects.create(email=f"staff{index}@example.com", organisation=org)
        Membership.objects.create(person=person, organisation=org, title="Buyer")
        Address.objects.create(organisation=org, line1=f"{index} River Walk", country="GB")
    assert cost() == few


def test_an_address_goes_only_to_a_person_you_may_read(family: dict[str, Any]) -> None:
    client = _client("customer", email="ana@example.com")
    mine = client.post(
        "/api/people-addresses/",
        {"person": str(family["keep"].pk), "line1": "4 Park Avenue", "country": "PT"},
        format="json",
    )
    assert mine.status_code == 201, mine.data
    theirs = client.post(
        "/api/people-addresses/",
        {"person": str(family["drop"].pk), "line1": "4 Park Avenue"},
        format="json",
    )
    assert theirs.status_code == 400
    assert {row["line1"] for row in client.get("/api/people-addresses/").data["results"]} == {
        "1 Mill Lane",
        "4 Park Avenue",
    }


# merge, duplicates, erase


def test_merge_needs_the_explicit_permission(family: dict[str, Any]) -> None:
    keep, drop = family["keep"], family["drop"]
    url = f"/api/people/{keep.pk}/merge-plan/"
    assert _client("staff").get(url, {"drop": str(drop.pk)}).status_code == 403  # "*" is not enough
    assert _client("viewer").get(url, {"drop": str(drop.pk)}).status_code == 403
    desk = _client("desk")
    plan = desk.get(url, {"drop": str(drop.pk)})
    assert plan.status_code == 200 and plan.data["allowed"] is True
    assert {"model": "helpdeskapp.Ticket", "field": "person", "kind": "foreign_key", "rows": 2} in (
        plan.data["moves"]
    )
    assert desk.get(url).status_code == 400
    merged = desk.post(f"/api/people/{keep.pk}/merge/", {"drop": str(drop.pk)}, format="json")
    assert merged.status_code == 200 and Ticket.objects.filter(person=keep).count() == 3
    again = desk.post(f"/api/people/{keep.pk}/merge/", {"drop": str(drop.pk)}, format="json")
    assert again.status_code == 404  # the merged record is gone from the list


def test_a_refused_merge_is_a_409_with_the_plan() -> None:
    first = Person.objects.create(email="ben@example.com", user=make_user("ben@example.com"))
    second = Person.objects.create(email="ben@example.org", user=make_user("ben@example.org"))
    response = _client("desk").post(
        f"/api/people/{first.pk}/merge/", {"drop": str(second.pk)}, format="json"
    )
    assert response.status_code == 409 and response.data["code"] == "E250"
    assert response.data["conflict"]["refusals"][0]["code"] == "E250"


def test_organisations_merge_through_the_api(family: dict[str, Any]) -> None:
    org, other = family["org"], family["other"]
    admin = _client("admin")
    response = admin.post(f"/api/organisations/{org.pk}/merge/", {"drop": str(other.pk)})
    assert response.status_code == 200, response.data
    assert _client("desk").post(
        f"/api/organisations/{org.pk}/merge/", {"drop": str(org.pk)}
    ).status_code in (403, 404)


def test_duplicates_and_erase(family: dict[str, Any]) -> None:
    groups = _client("desk").get("/api/people/duplicates/").data
    assert groups == [
        {"rule": "email_tag", "people": [str(family["keep"].pk), str(family["drop"].pk)]}
    ]
    assert _client("viewer").get("/api/people/duplicates/").status_code == 403
    url = f"/api/people/{family['drop'].pk}/erase/"
    assert _client("staff").post(url).status_code == 403  # "*" never reaches erase
    assert _client("admin").post(url).status_code == 204
    assert Person._base_manager.get(pk=family["drop"].pk).erased_at is not None
