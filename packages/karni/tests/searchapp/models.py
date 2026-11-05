"""A product catalog that opts into cross-model search (``class Karni: search``).

The keys follow ``KARNI_TEST_PK`` like the test app's API models, so the
integer-key run searches integer-keyed rows.
"""

from __future__ import annotations

from django.db import models

from tests.testapp.models import ApiBase


class Supplier(ApiBase):
    """Searched by name, shown with its city. Everyone signed in may list them."""

    name = models.CharField(max_length=200)
    city = models.CharField(max_length=100, blank=True)

    class Karni:
        search = {"fields": ["name"], "title": "name", "subtitle": "city"}

    def __str__(self) -> str:
        return self.name


class Product(ApiBase):
    """Searched by name and SKU, shown with its supplier's name, weighted up. Public."""

    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=40, blank=True)
    description = models.TextField(blank=True)
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.SET_NULL)

    class Karni:
        search = {
            "fields": ["name", "sku"],
            "title": "name",
            "subtitle": "supplier__name",
            "weight": 2,
        }

    def __str__(self) -> str:
        return self.name


class Note(ApiBase):
    """Each user lists only the notes they wrote (``Owned()``)."""

    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)

    class Karni:
        search = {"fields": ["title", "body"]}

    def __str__(self) -> str:
        return self.title


class Report(ApiBase):
    """Only staff may list reports (``HasRole("staff")``)."""

    title = models.CharField(max_length=200)

    class Karni:
        search = {"fields": ["title"], "weight": 0.5}

    def __str__(self) -> str:
        return self.title


class Region(ApiBase):
    """Declares search but no viewset serves it (``karni.W591``)."""

    name = models.CharField(max_length=100)

    class Karni:
        search = {"fields": ["name"]}

    def __str__(self) -> str:
        return self.name
