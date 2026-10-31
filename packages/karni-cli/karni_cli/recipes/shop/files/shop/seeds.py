"""shop demo data for karni seed. Each seeder extends the one karni build writes in
shop/karni/seeds.py: steer a field's values here.
"""

from decimal import Decimal

import factory

from shop.karni import seeds as karni


class CategorySeeder(karni.CategorySeeder):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class ProductSeeder(karni.ProductSeeder):
    """Products on sale, most of them in stock."""

    active = True
    stock = factory.Iterator([0, 5, 12, 40])


class CartSeeder(karni.CartSeeder):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class CartItemSeeder(karni.CartItemSeeder):
    """The base class comes from karni.yaml (karni build). Add your own code here."""

    quantity = factory.Iterator([1, 1, 2, 3])


class OrderSeeder(karni.OrderSeeder):
    """Orders start empty: their items make the total."""

    total = Decimal("0.00")


class OrderItemSeeder(karni.OrderItemSeeder):
    """Each item at its product's price."""

    quantity = factory.Iterator([1, 1, 2, 3])
    unit_price = factory.LazyAttribute(lambda item: item.product.price)
