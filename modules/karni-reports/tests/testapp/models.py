"""The project under test: a product catalog.

``KARNI_TEST_PK=bigint`` puts the models on integer keys (CI runs the suite
both ways), so the reports of rows with either key type are covered.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, TypeAlias

from django.conf import settings
from django.db import models
from karni.models import BaseModel, BigIntBaseModel

#: The key type of the catalog's models: ``uuid`` (the default) or ``bigint``.
TEST_PK = os.environ.get("KARNI_TEST_PK", "uuid")
if TEST_PK not in ("uuid", "bigint"):
    raise RuntimeError(f"KARNI_TEST_PK must be uuid or bigint, not {TEST_PK!r}.")

if TYPE_CHECKING:
    CatalogBase: TypeAlias = BaseModel  # noqa: UP040 - a class statement needs a real alias
else:
    CatalogBase = BigIntBaseModel if TEST_PK == "bigint" else BaseModel


class Category(CatalogBase):
    """Anyone may read a category."""

    name = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.name


class Product(CatalogBase):
    """A product its owner reads and writes."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self) -> str:
        return self.name
