"""The demo data karni seed writes: real-sounding, and the same on every run."""

import datetime as dt
import re
from typing import Any

import pytest
from django.apps import apps
from karni.seeding import seed, seeders

from portal.models import Dataset, Indicator, Region, Sector
from portal.seeds import FLAT, REGIONS, SECTORS

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
    first = snapshot("portal")
    for model in (Region, Sector, Dataset, Indicator):
        assert model.objects.count() == seeders()[model].row_count(10)
    seed(seed=7, now=NOW, reset=True)
    assert snapshot("portal") == first
    seed(seed=8, now=NOW, reset=True)
    assert snapshot("portal") != first


def test_datasets_sit_in_their_topic_and_indicators_in_their_dataset_range() -> None:
    seed(seed=3, now=NOW, reset=True)
    measures = {measure.title: (topic, measure) for _, topic, measure in FLAT}
    assert set(Region.objects.values_list("name", flat=True)) <= (
        set(REGIONS) | {c for cs in REGIONS.values() for c in cs}
    )
    assert set(Sector.objects.values_list("name", flat=True)) <= (
        set(SECTORS) | {t for ts in SECTORS.values() for t in ts}
    )
    for dataset in Dataset.objects.all():
        topic, measure = measures[dataset.title]
        assert [row.name for row in dataset.sector.all()] == [topic]
    for indicator in Indicator.objects.select_related("dataset", "region"):
        topic, measure = measures[indicator.dataset.title]
        assert indicator.sector.name == topic and indicator.unit == measure.unit
        assert measure.low <= float(indicator.value) <= measure.high
        assert indicator.region in indicator.dataset.region.all()


def test_a_larger_count_repeats_names_with_a_number_and_never_clashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(seeders()[Region].Meta, "count", 90)
    monkeypatch.setattr(seeders()[Dataset].Meta, "count", 40)
    monkeypatch.setattr(seeders()[Indicator].Meta, "count", 500)
    seed(seed=1, now=NOW, reset=True)
    names = list(Region.objects.values_list("name", flat=True))
    assert len(names) == len(set(names)) == 90
    titles = list(Dataset.objects.values_list("title", flat=True))
    assert len(titles) == len(set(titles)) == 40
    assert Indicator.objects.count() == 500
