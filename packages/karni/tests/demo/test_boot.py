"""Boot: migrate, then seed an empty database, keep fresh data, reset old data."""

from __future__ import annotations

import datetime as dt
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from django.utils import timezone

from karni.demo import accounts, reset
from karni.exceptions import KarniCommandError
from tests.testapp.models import Venue

from .conftest import CUSTOMER, STAFF, user, write_stamp


def boot(*args: str) -> str:
    out = StringIO()
    call_command("karni_demo_boot", "--no-migrate", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_an_empty_database_is_seeded_with_the_fixed_seed(demo: Any) -> None:
    assert not accounts.seeded()

    output = boot()

    assert "Empty database, seeded" in output
    assert Venue.objects.count() == 3
    assert user(STAFF).is_superuser and user(CUSTOMER).check_password("karni-password")
    assert reset.last_reset() is not None


@pytest.mark.django_db
def test_a_boot_keeps_data_younger_than_the_reset_period(seeded: dt.datetime) -> None:
    Venue.objects.create(name="Added by a visitor", city="X")

    assert "Demo data kept" in boot()
    assert Venue.objects.filter(name="Added by a visitor").exists()


@pytest.mark.django_db
def test_a_boot_resets_data_older_than_the_reset_period(seeded: dt.datetime) -> None:
    Venue.objects.create(name="Added by a visitor", city="X")
    write_stamp(timezone.now() - dt.timedelta(hours=25))

    assert "older than 24 hours, reset" in boot()
    assert not Venue.objects.filter(name="Added by a visitor").exists()
    assert Venue.objects.count() == 3


@pytest.mark.django_db
def test_a_boot_adds_an_account_listed_after_the_first_boot(seeded: dt.datetime, demo: Any) -> None:
    demo.KARNI_DEMO_ACCOUNTS = [
        *demo.KARNI_DEMO_ACCOUNTS,
        {"login": "analyst@example.com", "label": "Analyst", "roles": []},
    ]

    boot()

    assert accounts.find("analyst@example.com") is not None


@pytest.mark.django_db
def test_boot_refuses_outside_demo_mode_in_production(demo: Any) -> None:
    demo.KARNI_DEMO_MODE = False
    demo.DEBUG = False
    with pytest.raises(KarniCommandError, match="KARNI_DEMO_MODE") as caught:
        boot()
    assert caught.value.code == "E951"


@pytest.mark.django_db
def test_boot_runs_in_development_without_demo_mode(demo: Any) -> None:
    demo.KARNI_DEMO_MODE = False
    demo.DEBUG = True
    assert "seeded" in boot()
