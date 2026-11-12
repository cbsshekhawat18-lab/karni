"""The demo data karni seed writes: real-sounding, and the same on every run."""

import datetime as dt
import re
from decimal import Decimal
from typing import Any

import pytest
from django.apps import apps
from karni.seeding import seed, seeders

from market.models import Listing, Order, Seller
from market.seeds import SELLERS

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
    first = snapshot("market")
    for model in (Seller, Listing, Order):
        assert model.objects.count() == seeders()[model].row_count(10)
    seed(seed=7, now=NOW, reset=True)
    assert snapshot("market") == first
    seed(seed=8, now=NOW, reset=True)
    assert snapshot("market") != first


def test_listings_fit_their_seller_and_orders_cost_their_listing() -> None:
    seed(seed=3, now=NOW, reset=True)
    shops = {shop.name: shop for shop in SELLERS}
    assert set(Seller.objects.values_list("name", flat=True)) <= set(shops)
    for listing in Listing.objects.select_related("seller"):
        entry = next(
            i for i in shops[listing.seller.name].listings if i[0] == listing.title
        )
        assert listing.price == Decimal(entry[1]) and listing.description == entry[2]
    for order in Order.objects.select_related("listing"):
        assert order.amount == order.listing.price * order.quantity
        assert 1 <= order.quantity <= 3 and order.listing.active


def test_a_larger_count_repeats_names_with_a_number_and_never_clashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(seeders()[Seller].Meta, "count", 8)
    monkeypatch.setattr(seeders()[Listing].Meta, "count", 100)
    seed(seed=1, now=NOW, reset=True)
    names = list(Seller.objects.values_list("name", flat=True))
    assert len(names) == len(set(names)) == 8
    titles = list(Listing.objects.values_list("title", flat=True))
    assert len(titles) == len(set(titles)) == 100
