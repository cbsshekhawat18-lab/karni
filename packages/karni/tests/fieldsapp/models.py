"""Models using every portable Karni field (PostgreSQL-only ones are built in the tests).

* ``Product`` (BaseModel, soft-deletable): money with a fixed and a per-row
  currency, a percentage, a quantity, a country, a phone number, a queried
  JSON document, a generated search column and a slug built from the name;
* ``Customer`` (BaseModel): a case-insensitive unique email, live rows only;
* ``Account`` (no soft delete): the same email field, unique across all rows;
* ``Membership``: a two-field ``LiveUniqueConstraint``;
* ``LogEntry``: ``class Karni: append_only = True`` (BRIN on created_at).
"""

from __future__ import annotations

from decimal import Decimal

from django.db import models

from karni.fields import (
    CountryField,
    CurrencyField,
    EmailField,
    JSONField,
    LiveUniqueConstraint,
    MoneyField,
    PercentField,
    PhoneField,
    QuantityField,
    SearchField,
    SlugField,
)
from karni.models import BaseModel, TimestampedModel, UUIDModel


class Product(BaseModel):
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    slug = SlugField(populate_from="name")
    price = MoneyField(currency="EUR", min_value=0)
    currency = CurrencyField(default="EUR")
    cost = MoneyField(currency_field="currency", default=Decimal("0"))
    discount = PercentField(default=0)
    stock = QuantityField(default=0)
    made_in = CountryField(blank=True)
    phone = PhoneField(blank=True)
    meta = JSONField(default=dict, queried=True)
    search = SearchField(sources=["name", "description"], weights={"name": "A"})

    def __str__(self) -> str:
        return self.name


class Customer(BaseModel):
    email = EmailField(unique=True)
    name = models.CharField(max_length=100, blank=True)

    def __str__(self) -> str:
        return self.email


class Account(UUIDModel, TimestampedModel):
    email = EmailField(unique=True)

    def __str__(self) -> str:
        return self.email


class Membership(BaseModel):
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)

    class Meta(BaseModel.Meta):
        constraints = [LiveUniqueConstraint(fields=["customer", "product"])]


class LogEntry(UUIDModel, TimestampedModel):
    message = models.CharField(max_length=200)

    class Karni:
        append_only = True
