"""Two things to sell that are not a shop's products: a gadget and a workshop seat."""

from __future__ import annotations

from django.db import models
from karni.fields import CapacityField, MoneyField
from karni.models import BaseModel


class Gadget(BaseModel):
    """A thing on a shelf: stock that checkout holds, sent to an address."""

    name = models.CharField(max_length=100)
    sku = models.CharField(max_length=20, blank=True, default="")
    price = MoneyField(currency="EUR")
    sale_price = MoneyField(currency="EUR", null=True, blank=True)
    stock = models.PositiveIntegerField(default=0)
    available = CapacityField(total="stock")

    def __str__(self) -> str:
        return self.name


class Workshop(BaseModel):
    """A seat in a workshop on a day: seats that checkout holds, nothing to ship."""

    title = models.CharField(max_length=100)
    price = MoneyField(currency="EUR")
    seats = models.PositiveIntegerField(default=10)
    free_seats = CapacityField(total="seats")
    starts_at = models.DateTimeField()
    enrolled = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return self.title
