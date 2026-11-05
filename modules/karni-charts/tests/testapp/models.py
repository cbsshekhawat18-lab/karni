"""The project under test: a product catalog a chart reads."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from karni.aggregation import TextNumber
from karni.models import BaseModel


class Category(BaseModel):
    name = models.CharField(max_length=100)

    class Karni:
        natural_key = "name"

    def __str__(self) -> str:
        return self.name


class Product(BaseModel):
    """Aggregated by category, channel and launch date. The owner sees their own rows."""

    class Channel(models.TextChoices):
        ONLINE = "online", "Online"
        STORE = "store", "Store"

    name = models.CharField(max_length=100)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.ONLINE)
    launched_on = models.DateField(null=True, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    revenue_text = models.CharField(max_length=40, blank=True, default="")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Karni:
        owner_field = "owner"
        aggregate = {
            "group_by": ["category", "channel", "launched_on"],
            "values": ["price", "revenue"],
            "expressions": {"revenue": TextNumber("revenue_text")},
        }

    def __str__(self) -> str:
        return self.name


class Note(BaseModel):
    """No aggregation: never a chart's source."""

    text = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.text
