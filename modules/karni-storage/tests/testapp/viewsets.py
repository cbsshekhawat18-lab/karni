from __future__ import annotations

from karni.api import Access, BaseViewSet, Owned

from tests.testapp.models import Product


class ProductViewSet(BaseViewSet):
    model = Product
    access = Access(read=Owned("owner"), write=Owned("owner"))
