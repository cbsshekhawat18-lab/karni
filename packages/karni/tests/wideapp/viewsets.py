"""Viewsets of the wide-model suite, mounted by ``tests.wideapp.urls`` only.

``auto_register = False`` keeps them out of the main router (and of the
testapp OpenAPI snapshot the UI parser tests share).
"""

from __future__ import annotations

from karni.api import Access, Authenticated, BaseViewSet, Public
from tests.wideapp.models import Brand, Product

OPEN = Access(read=Public(), write=Authenticated())


# karni: allow(public-integer-key): the test API is public on purpose, with either key type
class ProductViewSet(BaseViewSet):
    model = Product
    access = OPEN
    search_fields = ["name", "overview"]
    auto_register = False


# karni: allow(public-integer-key): the test API is public on purpose, with either key type
class BrandViewSet(BaseViewSet):
    model = Brand
    access = OPEN
    auto_register = False
