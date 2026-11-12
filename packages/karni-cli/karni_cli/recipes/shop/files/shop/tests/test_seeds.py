"""The demo data karni seed writes: a shop that looks alive, the same on every run."""

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from karni.seeding import seed, seeders

from shop.models import Address, Category, Order, OrderItem, Product, ProductImage, Tag
from shop.seeds import CATALOG, STATES

pytestmark = pytest.mark.django_db

NOW = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
SHORT = {
    name: (Decimal(price), short)
    for children in CATALOG.values()
    for products in children.values()
    for name, price, short in products
}


def snapshot(app: str) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of every model of the app, but for the times a save stamps and the keys."""
    found: dict[str, list[tuple[Any, ...]]] = {}
    for model in apps.get_app_config(app).get_models():
        names = [
            field.attname
            for field in model._meta.concrete_fields
            if not getattr(field, "auto_now", False)
            and not getattr(field, "auto_now_add", False)
            and field.attname not in ("key", "token", "reserved_until")
            # a file keeps its name, but storage adds a suffix when the old one is still there
            and field.get_internal_type() not in ("FileField", "ImageField")
        ]
        rows = model._base_manager.values_list(*names)
        found[model.__name__] = sorted(tuple(map(str, row)) for row in rows)
    return found


def test_the_same_seed_gives_the_same_rows_and_the_yaml_counts() -> None:
    seed(seed=7, now=NOW, reset=True)
    first = snapshot("shop")
    for model in (Category, Tag, Product, ProductImage, Address, Order):
        assert model.objects.count() == seeders()[model].row_count(10), model
    seed(seed=7, now=NOW, reset=True)
    assert snapshot("shop") == first


def test_the_demo_shop_looks_alive() -> None:
    seed(seed=3, now=NOW, reset=True)
    # The categories are a tree, and every product sits in a leaf with its catalogue entry.
    tops = set(Category.objects.filter(parent__isnull=True).values_list("name", flat=True))
    assert tops == set(CATALOG)
    for product in Product.objects.prefetch_related("categories__parent"):
        [child] = product.categories.all()
        assert child.parent is not None and child.name in CATALOG[child.parent.name]
        name = product.name if product.name in SHORT else product.name.rsplit(" ", 1)[0]
        assert (product.price, product.short_description) == SHORT[name]
        assert product.image.name.endswith(".png") and product.sku
    # Some on sale, some sold out, some featured, one not for sale.
    products = list(Product.objects.all())
    assert any(product.on_sale() for product in products)
    assert any(product.available == 0 for product in products)
    assert any(product.featured for product in products)
    assert any(not product.active for product in products)
    # Orders in every state, each adding up, each with its payment.
    assert set(Order.objects.values_list("status", flat=True)) == set(STATES)
    for order in Order.objects.all():
        lines = OrderItem.objects.filter(order=order)
        assert lines.exists()
        assert order.total == sum((line.line_total for line in lines), Decimal("0.00"))
        assert order.payment is not None and order.payment.amount == order.total
    # The demo people have their roles, and the customer has orders and an address.
    users = get_user_model().objects
    customer = users.get(email="customer@example.com")
    staff = users.get(email="staff@example.com")
    assert customer.can("shop.order:view") and not customer.can("shop.order:change")
    assert staff.can("shop.order:change") and staff.can("shop.product:change")
    assert Order.objects.filter(customer=customer).count() >= len(STATES) // 2
    assert Address.objects.filter(customer=customer, is_default=True).count() == 1
