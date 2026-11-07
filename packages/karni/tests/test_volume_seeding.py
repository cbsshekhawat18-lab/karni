"""Volume seeding (experimental): bulk rows that keep their relations, and the ledger's refusal."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from karni.bulk_seeding import Ledger, time_class, volume_users
from karni.seeding import seed, volume_rows
from tests.perfapp.models import Chapter, Genre, Novel, Publisher, Specimen, Writer
from tests.testapp.models import Event, Tag, Venue

pytestmark = pytest.mark.django_db

BOOKS = ["perfapp.Publisher", "perfapp.Writer", "perfapp.Genre", "perfapp.Novel", "perfapp.Chapter"]


def test_volume_rows_keep_their_relations() -> None:
    report = seed(models=BOOKS, volume=120, batch_size=50)
    assert report.volume == 120
    assert report.rows == {label: 120 for label in BOOKS}
    # a seeder that overrides seed() keeps its row-by-row control
    assert "perfapp.Writer" not in report.bulk
    assert set(report.bulk) == set(BOOKS) - {"perfapp.Writer"}
    writers = set(Writer.objects.values_list("pk", flat=True))
    novels = set(Novel.objects.values_list("pk", flat=True))
    assert set(Novel.objects.values_list("writer_id", flat=True)) <= writers
    assert set(Chapter.objects.values_list("novel_id", flat=True)) <= novels
    # the parents spread: more than one writer, more than one novel are used
    assert Novel.objects.values("writer_id").distinct().count() > 10
    assert Novel.genres.through.objects.exists()
    assert Novel.genres.through.objects.values("genre_id").distinct().count() > 10
    # timestamps spread over the last weeks, as the demo seed does
    assert Chapter.objects.values("created_at").distinct().count() > 50
    assert "(bulk, " in report.render() and "(volume 120)" in report.render()
    data = report.to_dict()
    assert data["volume"] == 120 and set(data["timings"]) == set(BOOKS)


def test_a_self_relation_points_at_earlier_rows_and_one_to_one_targets_are_used_once() -> None:
    seed(models=["perfapp.Publisher", "perfapp.Genre"], volume=90, batch_size=30)
    report = seed(models=["perfapp.Specimen"], volume=80, batch_size=20)
    assert report.rows == {"perfapp.Specimen": 80}
    specimens = list(Specimen.objects.all())
    keys = {row.pk for row in specimens}
    parents = [row.parent_id for row in specimens if row.parent_id is not None]
    assert parents and set(parents) <= keys
    publishers = [row.publisher_id for row in specimens]
    assert len(set(publishers)) == len(publishers) == 80
    assert len({row.label for row in specimens}) == 80  # unique values stay unique


def test_the_same_seed_gives_the_same_volume_rows() -> None:
    seed(models=["testapp.Venue"], volume=40, seed=3)
    first = sorted(Venue.objects.values_list("name", flat=True))
    Venue.objects.all().delete()
    seed(models=["testapp.Venue"], volume=40, seed=3, reset=True)
    assert sorted(Venue.objects.values_list("name", flat=True)) == first


def test_a_count_at_the_threshold_takes_the_bulk_path(settings) -> None:
    settings.KARNI_SEED_BULK_THRESHOLD = 25
    below = seed(models=["testapp.Tag"], count=24)
    assert below.bulk == [] and Tag.objects.count() == 24
    at = seed(models=["testapp.Venue", "testapp.Event"], count=25)
    assert at.bulk == ["testapp.Venue", "testapp.Event"]
    assert Event.objects.count() == 25
    assert set(Event.objects.values_list("venue_id", flat=True)) - {None} <= set(
        Venue.objects.values_list("pk", flat=True)
    )


def test_volume_rows_per_model() -> None:
    from django.contrib.auth import get_user_model

    assert volume_rows(Tag, 1000) == 1000 and volume_rows(Publisher, 1000) == 1000
    assert volume_rows(get_user_model(), 100_000) == volume_users(100_000) == 1000
    assert volume_users(10) == 3
    assert [time_class(n) for n in (1000, 200_000, 2_000_000, 50_000_000)] == [
        "seconds",
        "about a minute",
        "minutes",
        "an hour or more",
    ]


def test_the_command_refuses_rows_no_seed_run_left(settings, tmp_path: Path) -> None:
    settings.DEBUG = True  # the fixture, not override_settings: nothing leaks to later tests
    settings.KARNI_SEED_LEDGER = str(tmp_path / "seeded.json")
    out = StringIO()
    call_command("karni_seed", "--model", "testapp.Tag", "--volume", "30", stdout=out)
    assert "with seed 0 (volume 30)" in out.getvalue() and "(bulk, " in out.getvalue()
    ledger = json.loads((tmp_path / "seeded.json").read_text())["databases"]
    assert list(ledger.values())[0]["testapp.Tag"] == 30
    # the seeder's own rows do not block another volume run
    call_command("karni_seed", "--model", "testapp.Tag", "--volume", "30", stdout=StringIO())
    assert Tag.objects.count() == 60
    # a row written by someone else does
    Tag.objects.create(name="real content")
    with pytest.raises(CommandError) as caught:
        call_command("karni_seed", "--model", "testapp.Tag", "--volume", "30", stdout=StringIO())
    message = str(caught.value)
    assert message.startswith("E473: Refusing to seed: these tables hold rows no seed run left")
    assert "testapp.Tag (61 rows, 60 left by seed runs)" in message
    assert Tag.objects.count() == 61
    call_command(
        "karni_seed", "--model", "testapp.Tag", "--volume", "5", "--force", stdout=StringIO()
    )
    assert Tag.objects.count() == 66
    call_command(
        "karni_seed", "--model", "testapp.Tag", "--volume", "5", "--reset", stdout=StringIO()
    )
    assert Tag.objects.count() == 5 and not Tag.objects.filter(name="real content").exists()
    assert Ledger.from_settings().seeded(Tag) == 5


def test_a_demo_run_feeds_the_ledger_and_without_one_a_table_must_be_empty(
    settings, tmp_path: Path
) -> None:
    settings.DEBUG = True
    settings.KARNI_SEED_LEDGER = str(tmp_path / "seeded.json")
    call_command("karni_seed", "--model", "perfapp.Genre", "--count", "4", stdout=StringIO())
    call_command("karni_seed", "--model", "perfapp.Genre", "--volume", "10", stdout=StringIO())
    assert Genre.objects.count() == 14
    settings.KARNI_SEED_LEDGER = False
    with pytest.raises(CommandError, match="E473"):
        call_command("karni_seed", "--model", "perfapp.Genre", "--volume", "10", stdout=StringIO())


@override_settings(DEBUG=True)
def test_volume_takes_a_positive_number() -> None:
    with pytest.raises(CommandError, match="E475"):
        call_command("karni_seed", "--volume", "0", stdout=StringIO())
    with pytest.raises(CommandError, match="E475"):
        call_command("karni_seed", "--volume", "10", "--batch-size", "0", stdout=StringIO())


def test_a_volume_run_on_a_model_it_cannot_fill_is_a_coded_error() -> None:
    """F14: --volume ended in a raw E610 traceback where a plain seed gives a one-line E613."""
    from karni.bulk_seeding import BulkSeeder
    from karni.exceptions import KarniImproperlyConfigured
    from karni.seeding import SeedError

    class Unfillable:
        @staticmethod
        def build() -> None:
            raise KarniImproperlyConfigured("cannot generate Genre.span.", code="E610")

    with pytest.raises(SeedError, match="perfapp.Genre: .*cannot generate") as caught:
        BulkSeeder.rows(object(), Genre, Unfillable, 3)  # type: ignore[arg-type]
    assert caught.value.code == "E613" and "karni make seeder Genre" in str(caught.value)


def test_a_field_the_factory_cannot_fill_is_e613_in_bulk_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bulk path names the model and the fix, as the row-by-row path does."""
    from karni.seeding import SeedError
    from karni.testing.values import ValueInference

    real = ValueInference.generator

    def blind(self: ValueInference, model: type, model_field: object) -> object:
        if model is Tag and getattr(model_field, "name", "") == "name":
            return None  # a field type inference does not know
        return real(self, model, model_field)

    monkeypatch.setattr(ValueInference, "generator", blind)
    with pytest.raises(SeedError, match="E613") as caught:
        seed(models=["testapp.Tag"], volume=10)
    assert "karni make seeder Tag" in str(caught.value) and "E610" in str(caught.value)
