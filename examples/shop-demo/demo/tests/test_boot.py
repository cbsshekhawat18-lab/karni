"""Boot: migrate, then seed an empty database, keep fresh data, reset old data."""

from __future__ import annotations

import datetime as dt
from io import StringIO
from typing import Any

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone
from karni.accounts import terms
from shop.models import Category, Order, Product

from demo import account, reset

from .conftest import write_stamp


def boot() -> str:
    out = StringIO()
    call_command("demo_boot", stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_an_empty_database_is_seeded_with_the_fixed_seed(demo: Any) -> None:
    assert account.find() is None

    output = boot()

    assert "Empty database, seeded" in output
    assert (Category.objects.count(), Product.objects.count(), Order.objects.count()) == (5, 40, 30)
    user = account.find()
    assert user is not None and user.check_password("karni-password")
    assert user.is_superuser and user.is_staff and user.is_active
    current = terms.config()
    assert current is not None and terms.has_accepted(user.pk, current.version)
    assert reset.last_reset() is not None


@pytest.mark.django_db
def test_the_same_seed_gives_the_same_rows(demo: Any) -> None:
    boot()
    first = sorted(Product.objects.values_list("pk", "name"))
    reset.reset()
    assert sorted(Product.objects.values_list("pk", "name")) == first


@pytest.mark.django_db
def test_a_boot_keeps_data_younger_than_the_reset_period(seeded: dt.datetime) -> None:
    Category.objects.create(name="Added by a visitor")

    output = boot()

    assert "Demo data kept" in output
    assert Category.objects.filter(name="Added by a visitor").exists()


@pytest.mark.django_db
def test_a_boot_resets_data_older_than_the_reset_period(seeded: dt.datetime) -> None:
    Category.objects.create(name="Added by a visitor")
    write_stamp(timezone.now() - dt.timedelta(hours=25))

    output = boot()

    assert "older than 24 hours, reset" in output
    assert not Category.objects.filter(name="Added by a visitor").exists()
    assert Category.objects.count() == 5


@pytest.mark.django_db
def test_boot_refuses_outside_demo_mode_in_production(settings: Any) -> None:
    settings.DEMO_MODE = False
    settings.DEBUG = False
    with pytest.raises(CommandError, match="DEMO_MODE"):
        boot()
