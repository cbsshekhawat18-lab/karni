"""The demo data karni seed writes: real-sounding, and the same on every run."""

import datetime as dt
import re
from decimal import Decimal
from typing import Any

import pytest
from django.apps import apps
from karni.seeding import seed, seeders

from shop.models import Category, Order, OrderItem, Product
from shop.seeds import CATALOG

pytestmark = pytest.mark.django_db

NOW = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
PRICES = {
    name: Decimal(price) for items in CATALOG.values() for name, price, _ in items
}


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
    first = snapshot("shop")
    for model in (Category, Product, Order, OrderItem):
        assert model.objects.count() == seeders()[model].row_count(10)
    seed(seed=7, now=NOW, reset=True)
    assert snapshot("shop") == first
    seed(seed=8, now=NOW, reset=True)
    assert snapshot("shop") != first


def test_products_have_names_prices_and_categories_that_fit() -> None:
    seed(seed=3, now=NOW, reset=True)
    for product in Product.objects.select_related("category"):
        assert product.category.name in CATALOG
        entry = next(e for e in CATALOG[product.category.name] if e[0] == product.name)
        assert product.price == Decimal(entry[1]) and product.description == entry[2]
    assert set(Category.objects.values_list("name", flat=True)) <= set(CATALOG)


def test_order_items_cost_their_products_price() -> None:
    seed(seed=3, now=NOW, reset=True)
    for item in OrderItem.objects.select_related("product"):
        assert item.unit_price == item.product.price == PRICES[item.product.name]


def test_a_larger_count_repeats_names_with_a_number_and_never_clashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(seeders()[Category].Meta, "count", 8)
    monkeypatch.setattr(seeders()[Product].Meta, "count", 100)
    seed(seed=1, now=NOW, reset=True)
    names = list(Product.objects.values_list("name", flat=True))
    assert len(names) == len(set(names)) == 100
    assert {n if n in PRICES else without_round(n) for n in names} <= set(PRICES)
    assert Category.objects.count() == 8
