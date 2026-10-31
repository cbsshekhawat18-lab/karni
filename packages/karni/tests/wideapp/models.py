"""A product catalog entry with 120 fields, the shape of a large app's main table.

``Product`` declares 120 fields: a name, a SKU, a brand, a status and a
grade, twelve markdown sections (:class:`~karni.fields.MarkdownField`), and
numbered columns of each common kind (decimals, integers, booleans, short
texts, dates, money, percentages), as wide tables have them. Its ``class
Karni`` declares ``field_groups`` and ``column_sets`` (:mod:`karni.layout`),
and the budget tests in ``tests/test_layout.py`` measure its API payloads.
The UI suite renders its OpenAPI document
(``tests/api/fixtures/schema.wideapp.json``).

Both models inherit :data:`tests.testapp.models.ApiBase`, so the suite runs
with either key type (``KARNI_TEST_PK``).
"""

from __future__ import annotations

from typing import Any

from django.db import models

from karni.fields import MarkdownField, MoneyField, PercentField
from tests.testapp.models import ApiBase

#: The markdown sections, in the order the model declares them.
SECTIONS = (
    "overview",
    "features",
    "specifications",
    "materials",
    "assembly",
    "care",
    "safety",
    "warranty",
    "shipping",
    "returns",
    "sustainability",
    "faq",
)


#: The choices of the grade column.
GRADES = [("a", "A"), ("b", "B"), ("c", "C")]


def numbered(prefix: str, count: int) -> list[str]:
    """``["price_01", "price_02", ...]``: the names of one kind of numbered column."""
    return [f"{prefix}_{index:02d}" for index in range(1, count + 1)]


def _columns(prefix: str, count: int, make: Any) -> dict[str, models.Field[Any, Any]]:
    return {name: make() for name in numbered(prefix, count)}


class Brand(ApiBase):
    """A product's brand: the relation target."""

    name = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.name


class Product(ApiBase):
    """120 fields, grouped into five sections plus the rest, with three column sets."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        RETIRED = "retired", "Retired"

    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=40)
    brand = models.ForeignKey(
        Brand, null=True, blank=True, on_delete=models.SET_NULL, related_name="products"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    grade = models.CharField(max_length=1, choices=GRADES, blank=True)

    overview = MarkdownField(blank=True)
    features = MarkdownField(blank=True)
    specifications = MarkdownField(blank=True)
    materials = MarkdownField(blank=True)
    assembly = MarkdownField(blank=True)
    care = MarkdownField(blank=True)
    safety = MarkdownField(blank=True)
    warranty = MarkdownField(blank=True)
    shipping = MarkdownField(blank=True)
    returns = MarkdownField(blank=True)
    sustainability = MarkdownField(blank=True)
    faq = MarkdownField(blank=True)

    # The numbered columns, declared in a loop: a class body's namespace is a dict.
    locals().update(
        {
            **_columns(
                "dimension",
                20,
                lambda: models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True),
            ),
            **_columns("metric", 20, lambda: models.IntegerField(null=True, blank=True)),
            **_columns("flag", 15, lambda: models.BooleanField(default=False)),
            **_columns("label", 28, lambda: models.CharField(max_length=100, blank=True)),
            **_columns("date", 10, lambda: models.DateField(null=True, blank=True)),
            **_columns("price", 6, lambda: MoneyField(currency="EUR", null=True, blank=True)),
            **_columns("rate", 4, lambda: PercentField(null=True, blank=True)),
        }
    )

    class Karni:
        """Five groups (the rest go into Other) and three column sets."""

        field_groups = {
            "Overview": ["name", "sku", "brand", "status", "overview", "features"],
            "Specifications": [
                "specifications",
                "materials",
                "assembly",
                *numbered("dimension", 20),
            ],
            "Financials": [*numbered("price", 6), *numbered("rate", 4)],
            "Content": [
                "care",
                "safety",
                "warranty",
                "shipping",
                "returns",
                "sustainability",
                "faq",
            ],
            "Measurements": numbered("metric", 20),
        }
        column_sets = {
            "default": ["name", "sku", "brand", "status", "price_01"],
            "financial": ["name", *numbered("price", 6), *numbered("rate", 4)],
            "logistics": ["name", *numbered("dimension", 3), "date_01"],
        }

    def __str__(self) -> str:
        return self.name
