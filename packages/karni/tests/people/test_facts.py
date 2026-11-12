"""Person facts: what two parts contribute, read in SQL without knowing who contributed them."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from karni import people
from karni.exceptions import KarniValueError
from karni.people.models import Person
from karni.people.registry import facts, register_fact, unregister_fact
from tests.loyaltyapp.models import Visit

pytestmark = pytest.mark.django_db


def test_each_part_contributes_its_facts_from_its_people_module() -> None:
    registered = facts()
    assert {"visits", "loyalty_spent", "last_visit", "open_tickets"} <= set(registered)
    assert registered["visits"].source == "loyaltyapp"
    assert registered["open_tickets"].source == "helpdeskapp"
    assert registered["loyalty_spent"].kind == "money"


def test_facts_of_two_parts_count_right_in_one_query(family: dict[str, Any]) -> None:
    keep, drop = family["keep"], family["drop"]
    with CaptureQueriesContext(connection) as queries:
        rows = {
            row.pk: row
            for row in Person.objects.with_facts(
                "visits", "loyalty_spent", "last_visit", "open_tickets"
            )
        }
    assert len(queries) == 1
    assert (rows[keep.pk].visits, rows[keep.pk].open_tickets) == (2, 1)
    assert Decimal(rows[keep.pk].loyalty_spent) == Decimal("25.00")
    assert (rows[drop.pk].visits, rows[drop.pk].open_tickets) == (1, 1)  # one ticket is closed
    assert rows[drop.pk].last_visit == dt.date(2026, 11, 3)
    nobody = Person.objects.create(email="wen@example.com")
    alone = Person.objects.with_facts("visits", "loyalty_spent", "last_visit").get(pk=nobody.pk)
    assert (alone.visits, Decimal(alone.loyalty_spent), alone.last_visit) == (0, Decimal(0), None)


def test_a_fact_filters_and_orders_in_the_database(family: dict[str, Any]) -> None:
    keep = family["keep"]
    regulars = Person.objects.with_facts("visits").filter(visits__gte=2)
    assert list(regulars) == [keep]
    ordered = Person.objects.with_facts("visits").order_by("-visits")
    assert ordered.first() == keep


def test_a_deleted_row_does_not_count(family: dict[str, Any]) -> None:
    Visit.objects.filter(person=family["keep"]).first().delete()  # type: ignore[union-attr]
    assert Person.objects.with_facts("visits").get(pk=family["keep"].pk).visits == 1


@pytest.mark.parametrize(
    ("name", "kind"),
    [("email", "count"), ("club_visits", "count"), ("2fast", "count"), ("a__b", "count")],
)
def test_a_fact_needs_a_name_of_its_own(name: str, kind: str) -> None:
    with pytest.raises(KarniValueError) as caught:
        register_fact(name, people.count_of(Visit), kind=kind)
    assert caught.value.code == "E257"


def test_a_fact_is_registered_once_unless_replaced() -> None:
    with pytest.raises(KarniValueError) as caught:
        register_fact("visits", people.count_of(Visit))
    assert caught.value.code == "E257"
    original = facts()["visits"]
    try:
        replaced = register_fact(
            "visits", people.count_of(Visit), label="Club visits", replace=True
        )
        assert facts()["visits"] is replaced and replaced.label == "Club visits"
    finally:
        unregister_fact("visits")
        register_fact(
            "visits",
            original.expression,
            label=original.label,
            kind=original.kind,
            source="loyaltyapp",
        )
    with pytest.raises(KarniValueError):
        register_fact("bad_kind", people.count_of(Visit), kind="colour")


def test_asking_for_an_unknown_fact_names_the_known_ones() -> None:
    with pytest.raises(KarniValueError) as caught:
        list(Person.objects.with_facts("lifetime_value"))
    assert caught.value.code == "E257" and "visits" in str(caught.value)


def test_the_fact_decorator_and_exists_builder() -> None:
    @people.fact("has_visited", kind="boolean", label="Has visited")
    def has_visited() -> Any:
        return people.exists_of(Visit)()

    try:
        person = Person.objects.create(email="xia@example.com")
        assert Person.objects.with_facts("has_visited").get(pk=person.pk).has_visited is False
        Visit.objects.create(person=person, visited_on=dt.date(2026, 11, 1))
        assert Person.objects.with_facts("has_visited").get(pk=person.pk).has_visited is True
    finally:
        unregister_fact("has_visited")
