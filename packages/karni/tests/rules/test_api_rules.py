"""karni.rules and the access additions through the API: the refusal each request gets."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from karni.testing.schema import generate_schema
from tests.rulesapp.models import Course, Enrolment, Item, Lesson, Purchase, Shop

pytestmark = [pytest.mark.django_db, pytest.mark.urls("tests.rulesapp.urls")]


def _user(email: str, *roles: str) -> Any:
    user = get_user_model().objects.create_user(email=email, password="x-Password-1")
    for role in roles:
        user.groups.add(Group.objects.get_or_create(name=role)[0])
    return user


def _client(user: Any = None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


@pytest.fixture
def seller() -> Any:
    return _user("seller@example.com")


@pytest.fixture
def buyer() -> Any:
    return _user("buyer@example.com")


@pytest.fixture
def staff() -> Any:
    return _user("staff@example.com", "staff")


@pytest.fixture
def item(seller: Any) -> Item:
    shop = Shop.objects.create(owner=seller, name="Corner")
    return Item.objects.create(shop=shop, title="Lamp", price=Decimal("20.00"))


def _code(response: Any, field: str | None = None) -> str:
    body = response.json()
    if field is not None:
        return str(body[field][0])[:4]
    detail = body.get("detail")
    return str(detail.get("code") if isinstance(detail, dict) else body.get("code") or detail)[:4]


# the written row stays inside its predicate (E134)


def test_a_row_written_outside_the_write_predicate_is_e134(item: Item, buyer: Any) -> None:
    payload = {"shop": str(item.shop.pk), "title": "Fake", "price": "5.00"}
    response = _client(buyer).post("/api/items/", payload, format="json")
    assert response.status_code == 403, response.content
    assert response.json()["detail"].startswith("E134: ")
    assert not Item.objects.filter(title="Fake").exists()
    own = Shop.objects.create(owner=buyer, name="Mine")
    payload["shop"] = str(own.pk)
    assert _client(buyer).post("/api/items/", payload, format="json").status_code == 201


def test_an_update_that_moves_the_row_away_is_e134(item: Item, buyer: Any, seller: Any) -> None:
    theirs = Shop.objects.create(owner=buyer, name="Theirs")
    response = _client(seller).patch(
        f"/api/items/{item.pk}/", {"shop": str(theirs.pk)}, format="json"
    )
    assert response.status_code == 403, response.content
    item.refresh_from_db()
    assert item.shop.owner == seller


# Where(Matching(...)): rows on a flag, every row to the owner and staff


def test_rows_on_a_flag_and_every_row_to_the_owner(item: Item, seller: Any, staff: Any) -> None:
    hidden = Item.objects.create(shop=item.shop, title="Old", price=Decimal("1.00"), active=False)
    anonymous = _client().get("/api/items/").json()["results"]
    assert [row["title"] for row in anonymous] == ["Lamp"]
    assert _client().get(f"/api/items/{hidden.pk}/").status_code == 404
    mine = {row["title"] for row in _client(seller).get("/api/items/").json()["results"]}
    assert mine == {"Lamp", "Old"}
    assert len(_client(staff).get("/api/items/").json()["results"]) == 2


def test_rows_read_through_a_reverse_relation(buyer: Any, seller: Any) -> None:
    course = Course.objects.create(title="Pottery")
    lesson = Lesson.objects.create(course=course, title="Clay")
    assert _client(buyer).get(f"/api/lessons/{lesson.pk}/").status_code == 404
    Enrolment.objects.create(course=course, student=buyer)
    assert _client(buyer).get(f"/api/lessons/{lesson.pk}/").status_code == 200
    assert _client(seller).get(f"/api/lessons/{lesson.pk}/").status_code == 404


# assign (E135)


def test_the_owner_is_the_caller_unless_assign_admits(item: Item, buyer: Any, staff: Any) -> None:
    other = _user("other@example.com")
    payload = {"item": str(item.pk), "buyer": str(other.pk)}
    refused = _client(buyer).post("/api/purchases/", payload, format="json")
    assert refused.status_code == 403 and refused.json()["detail"].startswith("E135: ")
    own = _client(buyer).post("/api/purchases/", {"item": str(item.pk)}, format="json")
    assert own.status_code == 201, own.content
    assert own.json()["buyer"] == str(buyer.pk)
    for_other = _client(staff).post("/api/purchases/", payload, format="json")
    assert for_other.status_code == 201, for_other.content
    assert Purchase.objects.get(pk=for_other.json()["id"]).buyer == other
    move = _client(buyer).patch(
        f"/api/purchases/{own.json()['id']}/", {"buyer": str(other.pk)}, format="json"
    )
    assert move.status_code == 403 and move.json()["detail"].startswith("E135: ")


# rules through the API: 400 on the field


def test_rule_refusals_are_400_on_the_field(item: Item, buyer: Any, seller: Any) -> None:
    low = _client(seller).post(
        "/api/items/", {"shop": str(item.shop.pk), "title": "Free", "price": "0"}, format="json"
    )
    assert low.status_code == 400 and _code(low, "price") == "E990"
    client = _client(buyer)
    first = client.post("/api/purchases/", {"item": str(item.pk)}, format="json")
    again = client.post("/api/purchases/", {"item": str(item.pk)}, format="json")
    assert again.status_code == 400 and _code(again, "item") == "E991"
    zero = client.patch(f"/api/purchases/{first.json()['id']}/", {"quantity": 0}, format="json")
    assert zero.status_code == 400 and _code(zero, "quantity") == "E990"
    other = Item.objects.create(shop=item.shop, title="Desk", price=Decimal("5.00"))
    frozen = client.patch(
        f"/api/purchases/{first.json()['id']}/", {"item": str(other.pk)}, format="json"
    )
    assert frozen.status_code == 400 and _code(frozen, "item") == "E994"
    own_item = _client(seller).post("/api/purchases/", {"item": str(item.pk)}, format="json")
    assert own_item.status_code == 400 and _code(own_item, "item") == "E993"


def test_the_schema_publishes_number_limits() -> None:
    schema = generate_schema("tests.rulesapp.urls")
    stock = schema["components"]["schemas"]["RulesappItem"]["properties"]["stock"]
    assert stock.get("minimum") == 0 and stock.get("maximum") == 1000


# delete (access.delete and Karni.delete)


def test_delete_by_role_and_by_state(item: Item, buyer: Any, staff: Any) -> None:
    pending = Purchase.objects.create(item=item, buyer=buyer)
    assert _client(buyer).delete(f"/api/purchases/{pending.pk}/").status_code == 403
    pending.transition("status", "paid")
    refused = _client(staff).delete(f"/api/purchases/{pending.pk}/")
    assert refused.status_code == 409 and refused.json()["code"] == "E995"
    other = Purchase.objects.create(
        item=Item.objects.create(shop=item.shop, title="Desk", price=Decimal("5.00")), buyer=buyer
    )
    assert _client(staff).delete(f"/api/purchases/{other.pk}/").status_code == 204


def test_children_block_a_delete_with_409(item: Item, seller: Any) -> None:
    response = _client(seller).delete(f"/api/shops/{item.shop.pk}/")
    assert response.status_code == 409 and response.json()["code"] == "E995"


# row actions (E997)


def test_a_row_action_runs_only_from_its_states(item: Item, buyer: Any, staff: Any) -> None:
    purchase = Purchase.objects.create(item=item, buyer=buyer)
    client = _client(buyer)
    cancelled = client.post(f"/api/purchases/{purchase.pk}/cancel/")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    twice = client.post(f"/api/purchases/{purchase.pk}/cancel/")
    assert twice.status_code == 200 and twice.json()["status"] == "cancelled"
    pay = client.post(f"/api/purchases/{purchase.pk}/pay/")
    assert pay.status_code == 409 and pay.json()["code"] == "E997"
    assert pay.json()["conflict"]["from"] == ["pending"]


def test_a_row_action_follows_its_by_and_the_moves_it_makes(
    item: Item, buyer: Any, staff: Any
) -> None:
    purchase = Purchase.objects.create(item=item, buyer=buyer)
    assert _client(buyer).post(f"/api/purchases/{purchase.pk}/pay/").status_code == 200
    assert _client(buyer).post(f"/api/purchases/{purchase.pk}/pay/").status_code == 409
    assert _client(buyer).post(f"/api/purchases/{purchase.pk}/refund/").status_code == 403
    missing = _client(staff).post(f"/api/purchases/{purchase.pk}/refund/")
    assert missing.status_code == 400 and _code(missing, "reason") == "E996"
    done = _client(staff).post(
        f"/api/purchases/{purchase.pk}/refund/", {"reason": "damaged"}, format="json"
    )
    assert done.status_code == 200 and done.json()["status"] == "refunded"
    assert done.json()["refunded_at"]


def test_the_schema_lists_the_row_actions() -> None:
    schema = generate_schema("tests.rulesapp.urls")
    listed = schema["paths"]["/api/purchases/"]["get"]["x-karni-actions"]
    assert listed["refund"] == {
        "from": ["paid"],
        "to": "refunded",
        "field": "status",
        "by": {"role": ["staff"]},
        "requires": ["reason"],
    }
    assert listed["pay"]["to"] is None
    one = schema["paths"]["/api/purchases/{id}/cancel/"]["post"]["x-karni-action"]
    assert one["to"] == "cancelled"
    access = schema["paths"]["/api/items/"]["get"]["x-karni-access"]
    assert {"where": "active=True", "matching": {"active": True}} in access["any"]
