"""karni.seeding / ``manage.py karni_seed``: realistic, connected, reproducible demo data."""

from __future__ import annotations

import datetime as dt
import json
from io import StringIO
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.db import models
from django.test import override_settings
from django.test.utils import isolate_apps
from factory.random import reseed_random

from karni.seeding import (
    DEMO_LOGIN,
    SeedBuilder,
    Seeder,
    SeedError,
    _order,
    clear_cache,
    seed,
    seed_plan,
    seeders,
)
from karni.testing.factories import DEFAULT_PASSWORD, factory_for
from karni.testing.values import SAFE_DOMAINS, ValueInference
from tests.perfapp.models import Chapter, Genre, Loop, Novel, Publisher, Specimen, Writer
from tests.perfapp.seeds import PublisherSeeder, WriterSeeder
from tests.testapp.models import Event, Tag, Venue

pytestmark = pytest.mark.django_db

NOW = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
EVENTS = ["testapp.Venue", "testapp.Tag", "testapp.Event", get_user_model()]


def _dump(*model_classes: type[models.Model]) -> dict[str, list[dict[str, Any]]]:
    """Every row's fields (and to-many pks), ordered by pk — what a diff would compare."""
    out: dict[str, list[dict[str, Any]]] = {}
    for model in model_classes:
        rows = []
        for row in model._base_manager.order_by("pk"):
            data: dict[str, Any] = {
                f.attname: str(getattr(row, f.attname)) for f in model._meta.concrete_fields
            }
            for m2m in model._meta.many_to_many:
                data[m2m.name] = sorted(
                    str(pk) for pk in getattr(row, m2m.name).values_list("pk", flat=True)
                )
            rows.append(data)
        out[model._meta.label] = rows
    return out


def test_a_run_creates_connected_realistic_rows_and_a_demo_login() -> None:
    report = seed(models=EVENTS, count=8, seed=42, now=NOW)
    user_model = get_user_model()
    assert report.rows == {
        "karni_accounts.User": 3,
        "testapp.Tag": 8,
        "testapp.Venue": 8,
        "testapp.Event": 8,
    }
    demo = user_model.objects.get(email=DEMO_LOGIN)
    assert demo.check_password(DEFAULT_PASSWORD) and demo.is_staff and demo.is_superuser
    assert report.demo == DEMO_LOGIN and report.demo_password == DEFAULT_PASSWORD
    assert "staff" in report.roles and demo.groups.filter(name="staff").exists()
    assert "Log in as demo@example.com / karni-password (superuser, roles:" in report.render()
    others = user_model.objects.exclude(pk=demo.pk)
    assert all(user.email.split("@")[1] in SAFE_DOMAINS for user in others)
    events = list(Event.objects.all())
    assert {e.organizer_id for e in events} <= {
        *user_model.objects.values_list("pk", flat=True),
        None,
    }
    assert any(e.organizer_id == demo.pk for e in events), "the demo user owns some rows"
    assert {e.venue_id for e in events} - {None} <= set(Venue.objects.values_list("pk", flat=True))
    assert len({e.status for e in events}) == 2  # defaulted choices vary
    assert sum(e.tags.count() for e in events) > 0
    assert all(NOW < e.starts_at < NOW + dt.timedelta(days=61) for e in events)
    assert all(e.created_at < NOW for e in events)  # backdated, not "now"
    assert Tag.objects.count() == 8


def test_seed_logins_exist_with_their_roles(settings) -> None:
    from django.contrib.auth import get_user_model

    settings.KARNI_SEED_LOGINS = {"organizer@example.com": ["organizer"], "fan@example.com": []}
    report = seed(models=EVENTS, count=4, seed=1, now=NOW, reset=True)
    organizer = get_user_model().objects.get(email="organizer@example.com")
    assert [g.name for g in organizer.groups.all()] == ["organizer"]
    assert organizer.check_password("karni-password") and organizer.is_active
    assert report.logins == {"organizer@example.com": ["organizer"], "fan@example.com": []}
    assert "Also organizer@example.com / karni-password (roles: organizer)." in report.render()
    again = seed(models=EVENTS, count=4, seed=1, now=NOW, reset=False)
    assert get_user_model().objects.filter(email="organizer@example.com").count() == 1
    assert again.logins["fan@example.com"] == []


def test_the_same_seed_reproduces_the_same_rows() -> None:
    plan = [Venue, Tag, Event, get_user_model()]
    seed(models=EVENTS, count=6, seed=42, now=NOW)
    first = _dump(*plan)
    report = seed(models=EVENTS, count=6, seed=42, now=NOW, reset=True)
    assert report.reset == ["testapp.Event", "testapp.Venue", "testapp.Tag"]  # children first
    assert report.reused["karni_accounts.User"] == 3  # matched by login, never duplicated
    assert report.demo_password is None  # an existing demo user keeps its password
    assert _dump(*plan) == first
    seed(models=EVENTS, count=6, seed=7, now=NOW, reset=True)
    assert _dump(*plan)["testapp.Event"] != first["testapp.Event"]


def test_without_reset_a_run_adds_rows_and_keeps_uniques_unique() -> None:
    seed(models=["perfapp.Genre", "perfapp.Chapter"], count=5, seed=1, now=NOW)
    seed(models=["perfapp.Genre", "perfapp.Chapter"], count=5, seed=1, now=NOW)
    assert Genre.objects.count() == 10  # explicit GenreFactory, unique names
    assert Chapter.objects.count() == 10
    pairs = list(Chapter.objects.values_list("novel_id", "number"))
    assert len(set(pairs)) == 10  # unique (novel, number)


def test_a_seeded_uuid_key_an_earlier_run_used_is_replaced() -> None:
    # Each `karni seed` is a new process, so the same seed draws the same UUID
    # keys again; a key already in the table must give way to a fresh one, or
    # re-running fails with E612 on the primary key.
    declaration = SeedBuilder(ValueInference(now=NOW)).declaration(Venue, Venue._meta.pk)
    reseed_random(0)
    key = declaration.function()
    factory_for(Venue).create(pk=key)
    reseed_random(0)
    again = declaration.function()
    assert again != key
    assert not Venue.objects.filter(pk=again).exists()


def test_seeders_pin_counts_values_and_take_over_creation() -> None:
    assert seeders()[Publisher] is PublisherSeeder and seeders()[Writer] is WriterSeeder
    report = seed(models=["perfapp.Publisher", "perfapp.Writer"], count=4, seed=3, now=NOW)
    assert report.rows == {"perfapp.Publisher": 3, "perfapp.Writer": 4}
    assert set(Publisher.objects.values_list("name", flat=True)) == {"Penguin", "Faber", "Verso"}
    assert Writer.objects.filter(name="Pinned Writer").count() == 1
    assert set(Writer.objects.values_list("publisher__name", flat=True)) <= {
        "Penguin",
        "Faber",
        "Verso",
    }  # relations come from the seeded pool


def test_one_to_one_targets_are_used_once() -> None:
    seed(models=["perfapp.Publisher", "perfapp.Genre", "perfapp.Specimen"], count=5, now=NOW)
    owners = list(Specimen.objects.values_list("publisher_id", flat=True))
    assert len(owners) == len(set(owners)) == 5  # 3 pooled publishers, then new ones


def test_a_count_of_zero_skips_a_model() -> None:
    class NoVenues(Seeder):
        class Meta:
            model = Venue
            count = 0

    clear_cache()
    try:
        registry = seeders()
        registry[Venue] = NoVenues
        report = seed(models=["testapp.Venue", "testapp.Tag"], count=2, now=NOW)
    finally:
        clear_cache()
    assert report.rows == {"testapp.Tag": 2} and not Venue.objects.exists()


def test_unseedable_models_name_the_fix() -> None:
    with pytest.raises(SeedError, match=r"perfapp.Loop: .*loops back.*Seeder.seed\(\)"):
        seed(models=[Loop], count=1)
    with pytest.raises(SeedError, match="no such model"):
        seed(models=["nope.Nothing"])


@isolate_apps("tests.perfapp")
def test_required_relation_loops_have_no_order() -> None:
    class Egg(models.Model):
        hen = models.ForeignKey("Hen", on_delete=models.CASCADE)

        class Meta:
            app_label = "perfapp"

    class Hen(models.Model):
        egg = models.ForeignKey(Egg, on_delete=models.CASCADE)
        nest = models.ForeignKey(Egg, null=True, on_delete=models.CASCADE, related_name="+")

        class Meta:
            app_label = "perfapp"

    with pytest.raises(SeedError, match="Required relations loop between perfapp.Egg, perfapp.Hen"):
        _order([Egg, Hen])


def test_the_plan_orders_targets_first_and_includes_users() -> None:
    plan = seed_plan()
    labels = [model._meta.label for model in plan]
    assert "karni_accounts.User" in labels and "testapp.Event" in labels
    assert labels.index("testapp.Venue") < labels.index("testapp.Event")
    assert labels.index("perfapp.Novel") < labels.index("perfapp.Chapter")
    assert seed_plan([Chapter, Novel]) == [Novel, Chapter]


def test_the_management_command() -> None:
    with pytest.raises(CommandError, match="DEBUG is False"):
        call_command("karni_seed", "--model", "testapp.Tag")
    out = StringIO()
    call_command("karni_seed", "--model", "testapp.Tag", "--count", "2", "--force", stdout=out)
    assert "Seeded 1 model(s) with seed 0 (count 2)" in out.getvalue()
    out = StringIO()
    with override_settings(DEBUG=True):
        call_command(
            "karni_seed", "--model", "testapp.Tag", "--count", "3", "--seed", "9", "--json",
            stdout=out,
        )  # fmt: skip
    data = json.loads(out.getvalue())
    assert data["rows"] == {"testapp.Tag": 3} and data["seed"] == 9
    with override_settings(DEBUG=True), pytest.raises(CommandError, match="no such model"):
        call_command("karni_seed", "--model", "nope.X")
