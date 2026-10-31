"""The project under test: a product catalog to extract rows into.

The API models switch their key type with ``KARNI_TEST_PK`` (``uuid``, the
default, or ``bigint``), so the extraction runs with both.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, TypeAlias

from django.db import models
from karni.models import BaseModel, BigIntBaseModel

TEST_PK = os.environ.get("KARNI_TEST_PK", "uuid")
if TEST_PK not in ("uuid", "bigint"):
    raise RuntimeError(f"KARNI_TEST_PK must be uuid or bigint, not {TEST_PK!r}.")

if TYPE_CHECKING:
    ApiBase: TypeAlias = BaseModel
else:
    ApiBase = BigIntBaseModel if TEST_PK == "bigint" else BaseModel


class Category(ApiBase):
    name = models.CharField(max_length=100, unique=True)

    class Meta(BaseModel.Meta):
        verbose_name_plural = "categories"

    class Karni:
        natural_key = "name"

    def __str__(self) -> str:
        return self.name


class Tag(ApiBase):
    name = models.CharField(max_length=50, unique=True)

    class Karni:
        natural_key = "name"

    def __str__(self) -> str:
        return self.name


class Supplier(ApiBase):
    """No natural key: a relation to it cannot be named in a text, so extraction leaves it out."""

    phone = models.CharField(max_length=30)

    def __str__(self) -> str:
        return self.phone


class Product(ApiBase):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    name = models.CharField(max_length=120)
    sku = models.CharField(max_length=30, unique=True, help_text="The stock keeping unit.")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    released_on = models.DateField(null=True, blank=True)
    featured = models.BooleanField(default=False)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.PROTECT)
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.PROTECT)
    tags = models.ManyToManyField(Tag, blank=True)
    specs = models.JSONField(default=dict, blank=True)
    manual = models.FileField(upload_to="manuals/", blank=True)

    class Karni:
        import_key = "sku"

    def __str__(self) -> str:
        return self.name


class Region(ApiBase):
    """A resource whose viewset turns the import off."""

    name = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.name
