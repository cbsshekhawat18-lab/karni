"""The reset every DEMO_RESET_HOURS: due by the clock, once across workers, back to the seed."""

from __future__ import annotations

import datetime as dt
import fcntl
from typing import Any

import pytest
from django.apps import apps
from django.test import Client
from karni_payments.models import Payment
from shop.models import Category, Product

from demo import reset

from .conftest import demo_user, write_stamp


def snapshot() -> dict[str, int]:
    """Rows per table of every model a reset touches, plus the demo account's."""
    found = {model._meta.label: model._base_manager.count() for model in reset.wiped_models()}
    found["users"] = apps.get_model("karni_accounts", "User")._base_manager.count()
    return found


@pytest.mark.django_db
def test_not_due_before_the_period_is_over(seeded: dt.datetime) -> None:
    Category.objects.create(name="Added by a visitor")

    assert reset.reset_if_due(now=seeded + dt.timedelta(hours=23, minutes=59)) is False

    assert Category.objects.filter(name="Added by a visitor").exists()
    assert reset.last_reset() == seeded


@pytest.mark.django_db
def test_due_after_the_period_puts_everything_back(seeded: dt.datetime) -> None:
    before = snapshot()
    product = Product.objects.order_by("pk").first()
    assert product is not None
    name = product.name
    Category.objects.create(name="Added by a visitor")
    Product.objects.filter(pk=product.pk).update(name="Renamed by a visitor")
    Payment.objects.create(amount="12.00", currency="usd", provider="test")
    demo = demo_user()
    demo.set_password("changed-somehow")
    demo.is_superuser = False
    demo.save()
    later = seeded + dt.timedelta(hours=24)

    assert reset.reset_if_due(now=later) is True

    assert snapshot() == before
    assert Product.objects.get(pk=product.pk).name == name
    assert not Payment.objects.exists()
    demo = demo_user()
    assert demo.check_password("karni-password") and demo.is_superuser
    assert reset.last_reset() == later
    assert reset.reset_if_due(now=later + dt.timedelta(hours=1)) is False


@pytest.mark.django_db
def test_only_one_worker_resets(seeded: dt.datetime) -> None:
    """Another process holds the lock: this one serves the old data and does not wait."""
    Category.objects.create(name="Added by a visitor")
    lock = reset.stamp_path().with_name(f"{reset.stamp_path().name}.lock")
    with lock.open("a") as other_worker:
        fcntl.flock(other_worker, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with reset.exclusive() as mine:
            assert mine is False
        assert reset.reset_if_due(now=seeded + dt.timedelta(hours=25)) is False
        fcntl.flock(other_worker, fcntl.LOCK_UN)

    assert Category.objects.filter(name="Added by a visitor").exists()
    assert reset.reset_if_due(now=seeded + dt.timedelta(hours=25)) is True


@pytest.mark.django_db
def test_a_request_resets_data_that_is_due(seeded: dt.datetime) -> None:
    Category.objects.create(name="Added by a visitor")
    write_stamp(seeded - dt.timedelta(hours=25))

    answer = Client().get("/api/categories/")

    assert answer.status_code == 200
    assert answer.json()["count"] == 5
    assert not Category.objects.filter(name="Added by a visitor").exists()


@pytest.mark.django_db
def test_a_request_checks_at_most_once_per_interval(seeded: dt.datetime, demo: Any) -> None:
    demo.DEMO_RESET_CHECK_SECONDS = 3600
    client = Client()
    client.get("/healthz")  # this worker's first check: not due
    Category.objects.create(name="Added by a visitor")
    write_stamp(seeded - dt.timedelta(hours=25))

    client.get("/api/categories/")

    assert Category.objects.filter(name="Added by a visitor").exists()


@pytest.mark.django_db
def test_nothing_resets_outside_demo_mode(seeded: dt.datetime, demo: Any) -> None:
    demo.DEMO_MODE = False
    Category.objects.create(name="Added by a visitor")
    write_stamp(seeded - dt.timedelta(hours=25))

    Client().get("/api/categories/")

    assert Category.objects.filter(name="Added by a visitor").exists()


@pytest.mark.django_db
def test_a_missing_or_broken_stamp_counts_as_due(demo: Any) -> None:
    assert reset.due() is True
    reset.stamp_path().write_text("not json")
    assert reset.last_reset() is None and reset.due() is True
