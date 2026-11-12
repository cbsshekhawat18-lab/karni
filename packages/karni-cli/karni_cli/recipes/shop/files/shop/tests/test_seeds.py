"""The demo data karni seed writes: a shop that looks alive, the same on every run."""

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core import mail
from karni.seeding import seed, seeders
from karni_commerce.models import Order

from shop.models import Category, Product, ProductImage, Shipment, Tag
from shop.seeds import CATALOG

pytestmark = pytest.mark.django_db

NOW = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
SHORT = {
    name: (Decimal(price), short)
    for children in CATALOG.values()
    for products in children.values()
    for name, price, short in products
}
VOLATILE = ("key", "token", "hold_until", "paid_at", "cancelled_at", "lines")


def snapshot(*labels: str) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of the apps' models, but for the times a save stamps and the keys."""
    found: dict[str, list[tuple[Any, ...]]] = {}
    for label in labels:
        for model in apps.get_app_config(label).get_models():
            names = [
                field.attname
                for field in model._meta.concrete_fields
                if not getattr(field, "auto_now", False)
                and not getattr(field, "auto_now_add", False)
                and field.attname not in VOLATILE
                and not field.attname.endswith("_at")
                and field.get_internal_type() not in ("FileField", "ImageField")
                and not field.is_relation
                and field.attname != "id"
            ]
            rows = model._base_manager.values_list(*names)
            found[model.__name__] = sorted(tuple(map(str, row)) for row in rows)
    return found


def test_the_same_seed_gives_the_same_rows_and_the_yaml_counts() -> None:
    seed(seed=7, now=NOW, reset=True)
    first = snapshot("shop", "karni_commerce")
    for model in (Category, Tag, Product, ProductImage):
        assert model.objects.count() == seeders()[model].row_count(10), model
    seed(seed=7, now=NOW, reset=True)
    assert snapshot("shop", "karni_commerce") == first
    assert mail.outbox == []  # the demo mails nobody


def test_the_demo_shop_looks_alive() -> None:
    seed(seed=3, now=NOW, reset=True)
    # The categories are a tree, and every product sits in a leaf of the catalogue.
    tops = set(
        Category.objects.filter(parent__isnull=True).values_list("name", flat=True)
    )
    assert tops == set(CATALOG)
    for product in Product.objects.prefetch_related("categories__parent"):
        [child] = product.categories.all()
        assert child.parent is not None and child.name in CATALOG[child.parent.name]
        name = product.name if product.name in SHORT else product.name.rsplit(" ", 1)[0]
        assert (product.price, product.short_description) == SHORT[name]
        assert product.image.name.endswith(".png") and product.sku
        assert 0 <= product.available <= product.stock
    products = list(Product.objects.all())
    assert any(product.on_sale() for product in products)
    assert any(product.available == 0 for product in products)
    assert any(product.featured for product in products)
    assert any(not product.active for product in products)
    # Orders in every money state, each adding up, and parcels in every state.
    assert set(Order.objects.values_list("status", flat=True)) >= {
        "pending",
        "paid",
        "failed",
        "cancelled",
        "refunded",
        "part_refunded",
    }
    for order in Order.objects.prefetch_related("lines"):
        assert order.total == sum(
            (line.line_total for line in order.lines.all()), Decimal("0.00")
        )
        if order.status != "pending" and order.status != "cancelled":
            assert order.payments.exists()
    assert set(Shipment.objects.values_list("status", flat=True)) >= {
        "processing",
        "shipped",
        "delivered",
    }
    # The demo people have their roles, and the customer has orders.
    users = get_user_model().objects
    customer = users.get(email="customer@example.com")
    staff = users.get(email="staff@example.com")
    manager = users.get(email="manager@example.com")
    assert not customer.can("karni_commerce.order:change")
    assert staff.can("karni_commerce.order:change") and staff.can("shop.product:change")
    assert not staff.can("karni_commerce.orderrefund:add")
    assert manager.can("karni_commerce.orderrefund:add")
    assert Order.objects.filter(user=customer).count() >= 3
