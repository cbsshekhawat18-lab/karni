"""Viewsets for the aggregations suite, mounted by ``tests.aggregateapp.urls`` only.

``auto_register = False`` keeps them out of the main router and of the
OpenAPI snapshot the UI parser tests share.
"""

from __future__ import annotations

from karni.aggregation import Aggregation
from karni.api import Access, BaseViewSet, HasRole, Owned
from tests.aggregateapp.models import Category, Product

#: The owner reads their own products, an analyst every product.
READERS = Access(read=Owned("owner") | HasRole("analyst"), write=HasRole("analyst"))


class ProductViewSet(BaseViewSet):
    """The model's ``class Karni: aggregate`` applies."""

    model = Product
    access = READERS
    auto_register = False
    search_fields = ("name",)


class NarrowProductViewSet(BaseViewSet):
    """The viewset's own declaration wins over the model's."""

    model = Product
    access = READERS
    auto_register = False
    aggregation = Aggregation(group_by=["channel"], metrics=["count"])


class CategoryViewSet(BaseViewSet):
    """No declaration: the aggregate action answers 404."""

    model = Category
    access = Access(read=HasRole("analyst"), write=HasRole("analyst"))
    auto_register = False
