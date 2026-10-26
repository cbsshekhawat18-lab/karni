"""``Karni.dashboard``: the normalized declaration, its E133 refusals, the schema extension."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.core import checks
from django.test import override_settings

from karni.checks import check_dashboards
from karni.dashboard import dashboard_spec
from karni.errorcodes import KarniError
from karni.testing.schema import generate_schema
from tests.lifecycleapp.models import Order, Room, Slot, Stock
from tests.testapp.models import Event, Stamp


def lifecycle_router() -> Any:
    """KARNI_API_ROUTER for the schema test: the lifecycle suite's own router."""
    from tests.lifecycleapp.urls import router

    return router


@pytest.fixture
def declare(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Set ``Model.Karni.dashboard`` for one test (a Karni class is added when missing)."""

    def apply(model: Any, value: Any) -> None:
        karni = getattr(model, "Karni", None)
        if karni is None:
            karni = type("Karni", (), {})
            monkeypatch.setattr(model, "Karni", karni, raising=False)
        monkeypatch.setattr(karni, "dashboard", value, raising=False)

    yield apply


def refusal(model: Any) -> str:
    with pytest.raises(KarniError) as caught:
        dashboard_spec(model)
    assert caught.value.code == "E133"
    return str(caught.value)


def test_a_model_without_a_declaration_is_not_on_the_dashboard() -> None:
    assert dashboard_spec(Stock) is None
    assert dashboard_spec(Room) is None


def test_true_fills_in_every_default_from_the_model() -> None:
    assert dashboard_spec(Order) == {
        "label": "Orders",
        "order": 0,
        "total": True,
        "new_days": 7,
        "date_field": "created_at",
        # the StateField, and its states that still need someone (not terminal)
        "by": "status",
        "values": ["draft", "confirmed"],
        "counts": [],
        "recent": 5,
        "columns": None,
    }


def test_a_dict_says_what_to_show(declare: Any) -> None:
    declare(
        Slot,
        {
            "label": "Bookings",
            "order": 2,
            "new_days": 0,
            "values": ["held", "cancelled"],
            "counts": {"Starting today": {"starts_at__date": "today"}, "Rooms": {"room": [1, 2]}},
            "recent": 10,
            "columns": ["room", "starts_at", "status"],
            "date_field": "starts_at",
        },
    )
    assert dashboard_spec(Slot) == {
        "label": "Bookings",
        "order": 2,
        "total": True,
        "new_days": 0,
        "date_field": "starts_at",
        "by": "status",
        "values": ["held", "cancelled"],
        "counts": [
            {"label": "Starting today", "params": {"starts_at__date": "today"}},
            {"label": "Rooms", "params": {"room": [1, 2]}},
        ],
        "recent": 10,
        "columns": ["room", "starts_at", "status"],
    }


def test_by_a_plain_choices_field_or_a_boolean(declare: Any) -> None:
    declare(Event, {"by": "status"})
    spec = dashboard_spec(Event)
    assert spec is not None and spec["values"] == ["draft", "published"]
    declare(Event, {"by": "is_public", "values": [True]})
    spec = dashboard_spec(Event)
    assert spec is not None and spec["by"] == "is_public" and spec["values"] == ["true"]


def test_false_leaves_the_model_out(declare: Any) -> None:
    declare(Order, False)
    assert dashboard_spec(Order) is None


@pytest.mark.parametrize(
    ("value", "words"),
    [
        ("yes", "must be True or a dict"),
        ({"columns": ["title"], "colour": "red"}, "unknown keys: colour"),
        ({"by": "titel"}, "by names 'titel', which is not a field of Order"),
        ({"by": "title"}, "which has no choices"),
        ({"values": ["shipped"]}, "values names 'shipped', which 'status' does not have"),
        ({"columns": ["title", "price"]}, "columns names 'price'"),
        ({"date_field": "title"}, "must be a date or datetime field"),
        ({"recent": 500}, "show at most 25 rows"),
        ({"recent": -1}, "recent must be a whole number of 0 or more"),
        ({"counts": {"Open": {}}}, "must be a non-empty dict of API filters"),
        ({"counts": {"Open": {"stauts": "draft"}}}, "counts['Open'] names 'stauts'"),
        ({"counts": ["draft"]}, "counts must map a label"),
        ({"label": ""}, "label must be text"),
    ],
)
def test_a_declaration_that_cannot_work_is_refused(declare: Any, value: Any, words: str) -> None:
    declare(Order, value)
    assert words in refusal(Order)


def test_new_days_needs_a_date_field(declare: Any) -> None:
    # Stamp has no created_at: no "new" count by default, and asking for one is refused.
    declare(Stamp, True)
    spec = dashboard_spec(Stamp)
    assert spec is not None and spec["new_days"] == 0 and spec["date_field"] is None
    declare(Stamp, {"new_days": 7})
    assert "new_days needs a date field" in refusal(Stamp)


def test_karni_check_reports_e133(declare: Any) -> None:
    declare(Order, {"by": "titel"})
    from django.apps import apps

    messages = check_dashboards([apps.get_app_config("lifecycleapp")])
    assert [m.id for m in messages] == ["karni.E133"]
    assert messages[0].level == checks.ERROR and messages[0].obj is Order


def test_karni_check_is_quiet_for_valid_declarations() -> None:
    assert check_dashboards() == []


@pytest.mark.django_db
@override_settings(KARNI_API_ROUTER="tests.test_dashboard.lifecycle_router")
def test_the_schema_publishes_the_declaration_on_the_list_operation(declare: Any) -> None:
    declare(Slot, {"by": "status", "counts": {"Today": {"starts_at__date": "today"}}})
    schema = generate_schema("tests.lifecycleapp.urls")
    orders = schema["paths"]["/api/orders/"]["get"]
    assert orders["x-karni-resource"] == "orders"
    assert orders["x-karni-dashboard"] == dashboard_spec(Order)
    slots = schema["paths"]["/api/slots/"]["get"]["x-karni-dashboard"]
    assert slots["counts"] == [{"label": "Today", "params": {"starts_at__date": "today"}}]
    # Only the list operation carries it, and a model that does not opt in has none.
    assert "x-karni-dashboard" not in schema["paths"]["/api/orders/{id}/"]["get"]
    assert "x-karni-dashboard" not in schema["paths"]["/api/stock/"]["get"]


@pytest.mark.django_db
@override_settings(KARNI_API_ROUTER="tests.test_dashboard.lifecycle_router")
def test_a_malformed_declaration_never_breaks_the_schema(declare: Any) -> None:
    declare(Order, {"by": "titel"})
    schema = generate_schema("tests.lifecycleapp.urls")
    assert "x-karni-dashboard" not in schema["paths"]["/api/orders/"]["get"]
