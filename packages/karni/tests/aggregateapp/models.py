"""A small product catalog for the aggregations suite (``tests/api/test_aggregate.py``).

``Category`` is a tree (``parent``), so ``category__parent`` is a relation
path, and its natural key is a ``code`` while people read its ``name``.
``Product`` has one field of every kind a group or a value can be: a
relation, a choice, a boolean, a date and a datetime, numbers, a number
stored as text (``revenue_text``), a field only one role reads
(``cost``, the ``staff`` role) and a write-only one (``supplier_code``). The models follow
``KARNI_TEST_PK`` like the API models of ``tests.testapp``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.db import models

from karni.aggregation import TextNumber
from karni.models import BaseModel, BigIntBaseModel
from tests.testapp.models import TEST_PK

if TYPE_CHECKING:
    ApiBase = BaseModel
else:
    ApiBase = BigIntBaseModel if TEST_PK == "bigint" else BaseModel


# karni: allow(hand-written-tree): a plain self-referencing key to group by in the aggregation tests
class Category(ApiBase):
    """A node of the category tree: ``code`` is its key, ``name`` what people read."""

    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=40, unique=True, null=True, blank=True)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )

    class Karni:
        natural_key = "code"

    def __str__(self) -> str:
        return self.name


class Product(ApiBase):
    """What the aggregate action groups and sums."""

    class Channel(models.TextChoices):
        ONLINE = "online", "Online"
        STORE = "store", "Store"

    name = models.CharField(max_length=100)
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="products"
    )
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.ONLINE)
    featured = models.BooleanField(default=False)
    launched_on = models.DateField(null=True, blank=True)
    listed_at = models.DateTimeField(null=True, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    units = models.PositiveIntegerField(default=0)
    revenue_text = models.CharField(max_length=40, blank=True, default="")
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    supplier_code = models.CharField(max_length=20, blank=True, default="")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    class APIMeta:
        write_only = ["supplier_code"]

    class Karni:
        owner_field = "owner"
        field_roles = {"cost": ["staff"]}
        aggregate = {
            "group_by": [
                "category",
                "category__parent",
                "category__name",
                "channel",
                "featured",
                "launched_on",
                "listed_at:month",
                "units",
                "cost",
            ],
            "values": ["price", "units", "revenue", "cost", "name", "category"],
            "expressions": {"revenue": TextNumber("revenue_text")},
        }

    def __str__(self) -> str:
        return self.name
