"""The API side: 400 naming the legal states, 409 naming the conflict, the schema's extensions."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from rest_framework.test import APIClient

from karni.testing.schema import generate_schema
from tests.lifecycleapp.models import HAS_RANGES, Order, Room, Stock

pytestmark = [pytest.mark.django_db, pytest.mark.urls("tests.lifecycleapp.urls")]


@pytest.fixture
def api() -> APIClient:
    user = get_user_model().objects.create_user(email="api@example.com", password="x-Password-1")
    client = APIClient()
    client.force_authenticate(user)
    return client


def _patch(api: APIClient, path: str, payload: dict[str, Any]) -> Any:
    return api.patch(path, payload, format="json")


# lifecycle: 400 on the field


def test_an_illegal_transition_is_a_400_naming_the_legal_states(api: APIClient) -> None:
    order = Order.objects.create(title="o")
    order.transition("status", "cancelled")
    response = _patch(api, f"/api/orders/{order.pk}/", {"status": "draft"})
    assert response.status_code == 400, response.content
    (message,) = response.json()["status"]
    assert message.startswith("E980: ")
    assert "terminal state" in message and "errors/#e980" in message
    assert Order.objects.get(pk=order.pk).status == "cancelled"


def test_a_legal_transition_through_the_api_is_recorded(api: APIClient) -> None:
    order = Order.objects.create(title="o")
    response = _patch(api, f"/api/orders/{order.pk}/", {"status": "confirmed"})
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "confirmed"
    from karni.audit.models import ChangeLog

    entry = ChangeLog.objects.for_object(order).get(action="transition")
    assert entry.diff == {"status": ["draft", "confirmed"]}
    assert entry.actor is not None and entry.actor.email == "api@example.com"


def test_creating_in_a_non_initial_state_is_a_400(api: APIClient) -> None:
    response = api.post("/api/orders/", {"title": "x", "status": "refunded"}, format="json")
    assert response.status_code == 400, response.content
    assert response.json()["status"][0].startswith("E982: ")
    assert Order.objects.count() == 0
    assert api.post("/api/orders/", {"title": "x"}, format="json").json()["status"] == "draft"


def test_a_custom_action_gets_the_same_400(api: APIClient) -> None:
    order = Order.objects.create(title="o")
    response = api.post(f"/api/orders/{order.pk}/confirm/", {"to": "refunded"}, format="json")
    assert response.status_code == 400, response.content
    assert response.json()["status"][0].startswith("E980: ")
    ok = api.post(f"/api/orders/{order.pk}/confirm/", {}, format="json")
    assert ok.status_code == 200 and ok.json()["status"] == "confirmed"


def test_a_state_changed_by_someone_else_is_a_409(
    api: APIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    order = Order.objects.create(title="o")
    from karni import guards

    real = guards.plan_write

    def racing(instance: Any, update_fields: Any = None) -> Any:
        plan = real(instance, update_fields)
        if isinstance(instance, Order) and not instance._state.adding:
            # another request confirms the order between this one's read and its write
            Order.objects.filter(pk=instance.pk).update(status="cancelled")
        return plan

    monkeypatch.setattr(guards, "plan_write", racing)
    response = _patch(api, f"/api/orders/{order.pk}/", {"status": "confirmed"})
    assert response.status_code == 409, response.content
    body = response.json()
    assert body["code"] == "E981" and body["field"] == "status"
    assert body["conflict"]["current"] == "cancelled"
    assert body["detail"].startswith("E981: ")


# capacity: 409 naming what is left


def test_buying_more_than_is_left_is_a_409_with_the_count(api: APIClient) -> None:
    stock = Stock.objects.create(name="VIP", quantity=2)
    assert api.post(f"/api/stock/{stock.pk}/buy/", {"quantity": 2}, format="json").json() == {
        "remaining": 0
    }
    response = api.post(f"/api/stock/{stock.pk}/buy/", {"quantity": 1}, format="json")
    assert response.status_code == 409, response.content
    body = response.json()
    assert body["code"] == "E985" and body["field"] == "remaining"
    assert body["conflict"] == {
        "resource": "lifecycleapp.Stock",
        "id": str(stock.pk),
        "field": "remaining",
        "remaining": 0,
        "requested": 1,
    }
    assert "is sold out" in body["detail"]


def test_the_counter_is_read_only_and_lowering_the_total_too_far_is_a_409(api: APIClient) -> None:
    created = api.post("/api/stock/", {"name": "GA", "quantity": 3}, format="json")
    assert created.status_code == 201 and created.json()["remaining"] == 3
    pk = created.json()["id"]
    ignored = _patch(api, f"/api/stock/{pk}/", {"remaining": 99})
    assert ignored.status_code == 200 and ignored.json()["remaining"] == 3
    api.post(f"/api/stock/{pk}/buy/", {"quantity": 2}, format="json")
    response = _patch(api, f"/api/stock/{pk}/", {"quantity": 1})
    assert response.status_code == 409, response.content
    assert response.json()["field"] == "quantity"
    assert "2 are already reserved" in response.json()["detail"]
    grown = _patch(api, f"/api/stock/{pk}/", {"quantity": 10})
    assert grown.status_code == 200 and grown.json()["remaining"] == 8  # 10 minus the 2 sold


# no_overlap: 409 naming the booking in the way (PostgreSQL)


@pytest.mark.skipif(connection.vendor != "postgresql", reason="EXCLUDE needs PostgreSQL")
@pytest.mark.skipif(not HAS_RANGES, reason="range columns need psycopg")
def test_a_double_booking_is_a_409_naming_the_existing_booking(api: APIClient) -> None:
    room = Room.objects.create(name="Blue")
    start = dt.datetime(2026, 10, 21, 10, tzinfo=dt.UTC)

    def book(hours: tuple[int, int]) -> Any:
        payload = {
            "room": str(room.pk),
            "during": {
                "lower": (start + dt.timedelta(hours=hours[0])).isoformat(),
                "upper": (start + dt.timedelta(hours=hours[1])).isoformat(),
            },
        }
        return api.post("/api/reservations/", payload, format="json")

    first = book((0, 2))
    assert first.status_code == 201, first.content
    assert first.json()["during"]["bounds"] == "[)"
    response = book((1, 3))
    assert response.status_code == 409, response.content
    body = response.json()
    assert body["code"] == "E984" and body["field"] == "during"
    assert body["conflict"]["existing"] == first.json()["id"]
    assert book((2, 3)).status_code == 201  # touching is fine
    backwards = api.post(
        "/api/reservations/",
        {
            "room": str(room.pk),
            "during": [start.isoformat(), (start - dt.timedelta(hours=1)).isoformat()],
        },
        format="json",
    )
    assert backwards.status_code == 400 and "starts after it ends" in str(backwards.json())


@pytest.mark.skipif(connection.vendor != "postgresql", reason="EXCLUDE needs PostgreSQL")
def test_a_pair_overlap_is_a_409_too(api: APIClient) -> None:
    room = Room.objects.create(name="Red")
    start = dt.datetime(2026, 10, 21, 10, tzinfo=dt.UTC)
    payload = {
        "room": str(room.pk),
        "starts_at": start.isoformat(),
        "ends_at": (start + dt.timedelta(hours=1)).isoformat(),
    }
    assert api.post("/api/slots/", payload, format="json").status_code == 201
    response = api.post("/api/slots/", payload, format="json")
    assert response.status_code == 409 and response.json()["field"] == "starts_at"


# the schema


def test_the_schema_carries_the_lifecycle_for_clients() -> None:
    schema = generate_schema("tests.lifecycleapp.urls")
    status = schema["components"]["schemas"]["LifecycleappOrder"]["properties"]["status"]
    assert status["x-karni-transitions"] == {
        "draft": ["confirmed", "cancelled"],
        "confirmed": ["cancelled", "refunded"],
        "cancelled": [],
        "refunded": [],
    }
    assert status["x-karni-initial"] == ["draft"]
    enum_ref = status["allOf"][0]["$ref"].rsplit("/", 1)[-1]
    assert schema["components"]["schemas"][enum_ref]["enum"] == [
        "draft",
        "confirmed",
        "cancelled",
        "refunded",
    ]
    stock = schema["components"]["schemas"]["LifecycleappStock"]["properties"]
    assert stock["remaining"]["readOnly"] is True
    if HAS_RANGES:
        during = schema["components"]["schemas"]["LifecycleappReservation"]["properties"]["during"]
        assert during["type"] == "object" and during["x-karni-range"] == "datetime"
        assert during["properties"]["lower"]["format"] == "date-time"
