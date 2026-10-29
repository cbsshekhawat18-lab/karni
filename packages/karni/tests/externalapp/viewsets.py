"""Viewsets for the external tables suite, mounted by ``tests.externalapp.urls`` only.

``auto_register = False`` keeps them out of the main router (and of the
OpenAPI snapshot the UI parser tests share).
"""

from __future__ import annotations

from karni.api import Access, BaseViewSet, Granted, HasRole
from tests.externalapp.models import ProductMapping, Region, RegionTotal, Sale, Stock, Target

ANALYSTS = Access(read=HasRole("analyst"), write=HasRole("analyst"))


class RegionViewSet(BaseViewSet):
    model = Region
    access = ANALYSTS
    auto_register = False


class SaleViewSet(BaseViewSet):
    model = Sale
    access = ANALYSTS
    auto_register = False
    search_fields = ("product",)


class LeakySaleViewSet(SaleViewSet):
    """Serves writes although Sale is read-only: what assert_crud must catch."""

    def is_read_only(self) -> bool:
        return False


class GrantedSaleViewSet(BaseViewSet):
    """Rows from the roles' grants: ``related:region`` reads ``user.region``."""

    model = Sale
    access = Granted()
    auto_register = False


class TargetViewSet(BaseViewSet):
    model = Target
    access = ANALYSTS
    auto_register = False


class RegionTotalViewSet(BaseViewSet):
    model = RegionTotal
    access = ANALYSTS
    auto_register = False


class StockViewSet(BaseViewSet):
    model = Stock
    access = ANALYSTS
    auto_register = False


class ProductMappingViewSet(BaseViewSet):
    model = ProductMapping
    access = ANALYSTS
    auto_register = False
