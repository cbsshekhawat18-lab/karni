"""Shared fixtures for the karni-charts suite: synced roles, people and a catalog."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from karni.accounts.roles import sync_roles
from karni.testing import user_with_roles

from karni_charts.models import Chart
from tests.testapp.models import Category, Product


@pytest.fixture(autouse=True)
def _roles(db: None) -> None:
    sync_roles()


@pytest.fixture
def analyst() -> Any:
    return user_with_roles("analyst")


@pytest.fixture
def owner() -> Any:
    return user_with_roles("user")


@pytest.fixture
def staff() -> Any:
    """An admin user who also reads every product (the analyst role)."""
    return user_with_roles("analyst", is_staff=True, is_superuser=True)


@pytest.fixture
def catalog(owner: Any) -> dict[str, Any]:
    """Five products: three online, two in a store, two of them the owner's."""
    lamps = Category.objects.create(name="Lamps")
    toys = Category.objects.create(name="Toys")
    rows = [
        ("Desk lamp", lamps, "online", dt.date(2024, 3, 1), "10.00", "$1.2K", owner),
        ("Floor lamp", lamps, "store", dt.date(2024, 8, 1), "30.00", "450", None),
        ("Kite", toys, "online", dt.date(2025, 2, 1), "8.00", "2,000", owner),
        ("Yo-yo", toys, "online", dt.date(2025, 5, 1), "2.00", "", None),
        ("Puzzle", toys, "store", dt.date(2025, 9, 1), "12.00", "1.5M", None),
    ]
    found = {}
    for name, category, channel, launched, price, revenue, who in rows:
        found[name] = Product.objects.create(
            name=name,
            category=category,
            channel=channel,
            launched_on=launched,
            price=Decimal(price),
            revenue_text=revenue,
            owner=who,
        )
    return found


@pytest.fixture
def chart() -> Chart:
    """Products per launch year, stacked by channel, narrowable by channel."""
    made = Chart(
        name="Launches per year",
        slug="launches-per-year",
        source="products",
        x_field="launched_on",
        x_bucket="year",
        y_metric="count",
        z_field="channel",
        z_mode="stack",
        allowed_filters=["channel", "launched_on__gte"],
    )
    made.full_clean()
    made.save()
    return made
