"""Deterministic rows of the wide model, for the payload budgets and the UI fixtures.

Every value is fixed, so a payload's size only changes when the model or the
API's output does: each markdown section is about 400 characters (a heading,
a paragraph and three bullets), each text column 20 to 30 characters.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from tests.wideapp.models import SECTIONS, Brand, Product, numbered


def section(name: str, index: int) -> str:
    """A markdown section of about 400 characters."""
    return (
        f"## {name.capitalize()} of product {index}\n\n"
        "This section describes the product in the words a catalog uses: what it is "
        "made of, how it is used and what it needs. It is long enough to wrap over "
        "several lines in a form and on a detail page.\n\n"
        "- The first point, with **bold** text\n"
        "- The second point, with a [link](https://example.com/catalog)\n"
        "- The third point, with `code`\n"
    )


def values(index: int) -> dict[str, Any]:
    """Every field of product ``index`` but the brand."""
    found: dict[str, Any] = {
        "name": f"Product {index:03d}",
        "sku": f"SKU-{index:05d}",
        "status": "active",
        "grade": "b",
    }
    found.update({name: section(name, index) for name in SECTIONS})
    found.update({name: Decimal("12.50") + index for name in numbered("dimension", 20)})
    found.update({name: 1000 + index for name in numbered("metric", 20)})
    found.update({name: index % 2 == 0 for name in numbered("flag", 15)})
    found.update({name: f"Label {name} of {index:03d}" for name in numbered("label", 28)})
    found.update({name: datetime.date(2026, 1, 1) for name in numbered("date", 10)})
    found.update({name: Decimal("199.99") for name in numbered("price", 6)})
    found.update({name: Decimal("12.50") for name in numbered("rate", 4)})
    return found


def make_products(count: int) -> list[Product]:
    """``count`` products of one brand, every field filled."""
    brand = Brand.objects.create(name="House brand")
    return [Product.objects.create(brand=brand, **values(index)) for index in range(count)]
