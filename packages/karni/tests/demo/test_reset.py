"""The reset every KARNI_DEMO_RESET_HOURS: due by the clock, once, back to the seed."""

from __future__ import annotations

import datetime as dt
import fcntl
from typing import Any

import pytest
from django.test import Client

from karni.accounts.permissions import assign_role
from karni.demo import accounts, reset
from tests.testapp.models import Tag, Venue

from .conftest import CUSTOMER, STAFF, user, write_stamp


def names() -> list[str]:
    return sorted(Venue.objects.values_list("name", flat=True))


@pytest.mark.django_db
def test_not_due_before_the_period_is_over(seeded: dt.datetime) -> None:
    Venue.objects.create(name="Added by a visitor", city="X")

    assert reset.reset_if_due(now=seeded + dt.timedelta(hours=23, minutes=59)) is False

    assert Venue.objects.filter(name="Added by a visitor").exists()
    assert reset.last_reset() == seeded


@pytest.mark.django_db
def test_due_after_the_period_puts_everything_back(seeded: dt.datetime) -> None:
    before = names()
    Venue.objects.create(name="Added by a visitor", city="X")
    Tag.objects.create(name="a tag nobody seeded")
    Venue.objects.filter(name=before[0]).update(name="Renamed by a visitor")
    customer = user(CUSTOMER)
    customer.set_password("changed-somehow")
    customer.save()
    assign_role(customer, "extra")
    later = seeded + dt.timedelta(hours=24)

    assert reset.reset_if_due(now=later) is True

    assert names() == before
    assert not Tag.objects.exists()  # tables the seed does not fill are emptied too
    customer = user(CUSTOMER)
    assert (
        customer.check_password("karni-password")
        and not customer.groups.filter(name="extra").exists()
    )
    assert reset.last_reset() == later
    assert reset.reset_if_due(now=later + dt.timedelta(hours=1)) is False


@pytest.mark.django_db
def test_accounts_are_kept_across_a_reset(seeded: dt.datetime) -> None:
    keys = {login: user(login).pk for login in (STAFF, CUSTOMER)}
    reset.reset()
    assert {login: user(login).pk for login in (STAFF, CUSTOMER)} == keys


@pytest.mark.django_db
def test_the_same_seed_gives_the_same_rows(seeded: dt.datetime) -> None:
    first = list(Venue.objects.order_by("name").values_list("name", "city"))
    reset.reset()
    assert list(Venue.objects.order_by("name").values_list("name", "city")) == first


@pytest.mark.django_db
def test_the_period_is_a_setting(seeded: dt.datetime, demo: Any) -> None:
    demo.KARNI_DEMO_RESET_HOURS = 2
    assert reset.due(now=seeded + dt.timedelta(hours=1, minutes=59)) is False
    assert reset.due(now=seeded + dt.timedelta(hours=2)) is True
    assert reset.next_reset() == seeded + dt.timedelta(hours=2)


@pytest.mark.django_db
def test_only_one_worker_resets(seeded: dt.datetime) -> None:
    """Another process holds the lock: this one serves the old data and does not wait."""
    Venue.objects.create(name="Added by a visitor", city="X")
    lock = reset.stamp_path().with_name(f"{reset.stamp_path().name}.lock")
    with lock.open("a") as other_worker:
        fcntl.flock(other_worker, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with reset.exclusive() as mine:
            assert mine is False
        assert reset.reset_if_due(now=seeded + dt.timedelta(hours=25)) is False
        fcntl.flock(other_worker, fcntl.LOCK_UN)

    assert Venue.objects.filter(name="Added by a visitor").exists()
    assert reset.reset_if_due(now=seeded + dt.timedelta(hours=25)) is True


@pytest.mark.django_db
def test_a_request_resets_data_that_is_due(seeded: dt.datetime) -> None:
    Venue.objects.create(name="Added by a visitor", city="X")
    write_stamp(seeded - dt.timedelta(hours=25))

    answer = Client().get("/api/venues/")

    assert answer.status_code == 200
    assert answer.json()["count"] == 3
    assert not Venue.objects.filter(name="Added by a visitor").exists()


@pytest.mark.django_db
def test_a_request_checks_at_most_once_per_interval(seeded: dt.datetime, demo: Any) -> None:
    demo.KARNI_DEMO_RESET_CHECK_SECONDS = 3600
    client = Client()
    client.get("/healthz")  # this worker's first check: not due
    Venue.objects.create(name="Added by a visitor", city="X")
    write_stamp(seeded - dt.timedelta(hours=25))

    client.get("/api/venues/")

    assert Venue.objects.filter(name="Added by a visitor").exists()


@pytest.mark.django_db
def test_a_reset_that_fails_is_logged_and_the_request_is_served(
    seeded: dt.datetime,
    demo: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(reset, "reset_if_due", broken)
    assert Client().get("/api/venues/").status_code == 200
    assert "demo data reset failed" in caplog.text


@pytest.mark.django_db
def test_nothing_resets_outside_demo_mode(seeded: dt.datetime, demo: Any) -> None:
    demo.KARNI_DEMO_MODE = False
    Venue.objects.create(name="Added by a visitor", city="X")
    write_stamp(seeded - dt.timedelta(hours=25))

    Client().get("/api/venues/")

    assert Venue.objects.filter(name="Added by a visitor").exists()


@pytest.mark.django_db
def test_a_missing_or_broken_stamp_counts_as_due(demo: Any) -> None:
    assert reset.due() is True
    reset.stamp_path().parent.mkdir(parents=True, exist_ok=True)
    reset.stamp_path().write_text("not json")
    assert reset.last_reset() is None and reset.due() is True


@pytest.mark.django_db
def test_the_default_seeder_is_karni_seed_with_the_fixed_seed(demo: Any) -> None:
    demo.KARNI_DEMO_SEEDER = ""
    demo.KARNI_DEMO_SEED = 5
    calls: list[dict[str, Any]] = []
    import karni.seeding as seeding

    class Report:
        def render(self) -> str:
            return "report"

    def fake(**kwargs: Any) -> Report:
        calls.append(kwargs)
        return Report()

    original = seeding.seed
    seeding.seed = fake  # type: ignore[assignment]
    try:
        assert reset.reseed() == "report"
    finally:
        seeding.seed = original
    assert calls == [{"seed": 5, "reset": True}]


@pytest.mark.django_db
def test_a_seeder_that_cannot_be_imported_raises_e952(demo: Any) -> None:
    from karni.exceptions import KarniImportError

    demo.KARNI_DEMO_SEEDER = "tests.demo.nothing.seed"
    with pytest.raises(KarniImportError) as caught:
        reset.reseed()
    assert caught.value.code == "E952"


@pytest.mark.django_db
def test_kept_apps_are_a_setting(seeded: dt.datetime, demo: Any) -> None:
    demo.KARNI_DEMO_KEEP_APPS = ["contenttypes", "auth", "sessions", "testapp"]
    Tag.objects.create(name="kept")
    reset.reset()
    assert Tag.objects.filter(name="kept").exists()
    assert accounts.seeded()
