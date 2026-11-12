"""The demo data karni seed writes: real-sounding, and the same on every run."""

import datetime as dt
import re
from typing import Any

import pytest
from django.apps import apps
from karni.seeding import seed, seeders

from bookings.models import Booking, Resource, Slot
from bookings.seeds import RESOURCES

pytestmark = pytest.mark.django_db

NOW = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)


def snapshot(app: str) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of every model of the app, but for the times a save stamps."""
    found: dict[str, list[tuple[Any, ...]]] = {}
    for model in apps.get_app_config(app).get_models():
        names = [
            field.attname
            for field in model._meta.concrete_fields
            if not getattr(field, "auto_now", False)
            and not getattr(field, "auto_now_add", False)
        ]
        rows = model._base_manager.values_list(*names)
        found[model.__name__] = sorted(tuple(map(str, row)) for row in rows)
    return found


def without_round(name: str) -> str:
    """A name without the number a repeat is tagged with (Name 2)."""
    return re.sub(r" \d+$", "", name)


def test_the_same_seed_gives_the_same_rows_and_the_yaml_counts() -> None:
    seed(seed=7, now=NOW, reset=True)
    first = snapshot("bookings")
    for model in (Resource, Slot, Booking):
        assert model.objects.count() == seeders()[model].row_count(10)
    seed(seed=7, now=NOW, reset=True)
    assert snapshot("bookings") == first
    seed(seed=8, now=NOW, reset=True)
    assert snapshot("bookings") != first


def test_slots_follow_their_resource_and_bookings_fit_the_slots() -> None:
    seed(seed=3, now=NOW, reset=True)
    offers = {offer.name: offer for offer in RESOURCES}
    assert set(Resource.objects.values_list("name", flat=True)) <= set(offers)
    for slot in Slot.objects.select_related("resource"):
        offer = offers[slot.resource.name]
        assert slot.capacity == offer.capacity
        assert slot.ends_at - slot.starts_at == dt.timedelta(minutes=offer.minutes)
        assert slot.starts_at.hour in offer.starts and slot.starts_at > NOW
        held = slot.booking_set.exclude(status="cancelled").count()
        assert slot.remaining == slot.capacity - held >= 0


def test_a_larger_count_repeats_names_with_a_number_and_never_overbooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(seeders()[Resource].Meta, "count", 9)
    monkeypatch.setattr(seeders()[Slot].Meta, "count", 20)
    monkeypatch.setattr(seeders()[Booking].Meta, "count", 400)  # more than the places
    seed(seed=1, now=NOW, reset=True)
    names = list(Resource.objects.values_list("name", flat=True))
    assert len(names) == len(set(names)) == 9
    assert {without_round(name) for name in names} <= {
        offer.name for offer in RESOURCES
    }
    assert Booking.objects.count() == 400
    assert not Slot.objects.filter(remaining__lt=0).exists()
