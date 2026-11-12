"""A small shop that declares every rule of karni.rules once.

``Shop`` and ``Item`` are a seller's; ``Purchase`` is a buyer's, with a
lifecycle; ``Review`` points at a purchase and an item that must agree;
``Course`` and ``Lesson`` show a move that needs a related row.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from karni.fields import MoneyField, StateField
from karni.models import BaseModel


class Shop(BaseModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    name = models.CharField(max_length=100)

    class Karni:
        owner_field = "owner"
        unique = [["owner"]]
        delete = {"blocked_by": ["Item"]}

    def __str__(self) -> str:
        return self.name


class Item(BaseModel):
    shop = models.ForeignKey(Shop, on_delete=models.PROTECT)
    title = models.CharField(max_length=100)
    price = MoneyField(currency="USD")
    stock = models.IntegerField(default=1)
    active = models.BooleanField(default=True)

    class Karni:
        owner_field = "shop__owner"
        bounds = {"price": {"min": "0.01"}, "stock": {"min": 0, "max": 1000}}

    def __str__(self) -> str:
        return self.title


class Purchase(BaseModel):
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    quantity = models.IntegerField(default=1)
    status = StateField(
        states=["pending", "paid", "cancelled", "refunded"],
        transitions={"pending": ["paid", "cancelled"], "paid": ["refunded"]},
    )
    reason = models.TextField(blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)
    wanted_by = models.DateField(null=True, blank=True)

    class Karni:
        owner_field = "buyer"
        bounds = {"quantity": {"min": 1}, "wanted_by": {"min": "$today"}}
        unique = [{"fields": ["item", "buyer"], "where": {"status": {"not": "cancelled"}}}]
        targets = {"item": {"active": True, "shop__owner": {"not": "$me"}}}
        frozen = {"item": True, "quantity": {"status": "paid"}}
        delete = {"when": {"status__in": ["pending", "cancelled"]}}
        moves = {"refunded": {"requires": ["reason"], "stamps": ["refunded_at"]}}


class Review(BaseModel):
    purchase = models.ForeignKey(Purchase, on_delete=models.PROTECT)
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    stars = models.IntegerField(default=5)

    class Karni:
        targets = {"item": {"pk": "$purchase__item_id"}}
        bounds = {"stars": {"min": 1, "max": 5}}


class Course(BaseModel):
    title = models.CharField(max_length=100)
    published = models.BooleanField(default=False)
    published_on = models.DateField(null=True, blank=True)

    class Karni:
        moves = {"published": {"needs": ["Lesson"], "stamps": ["published_on"]}}

    def __str__(self) -> str:
        return self.title


class Lesson(BaseModel):
    course = models.ForeignKey(Course, on_delete=models.PROTECT)
    title = models.CharField(max_length=100)
