"""The taxonomy resources, for ``tests/taxonomy/``.

* ``products`` — every product but the ones named ``Secret ...`` is readable
  (staff read them all), signed-in users write;
* ``regions`` — every region but the one coded ``hidden`` is readable;
* ``categories`` and ``suppliers`` — readable by anyone;
* ``scoped/products`` — ``Granted()``, for the ``tree:region`` scope, on its
  own router (``get_scope_router``) so each router serves a model once.

``ROLES`` is the ``KARNI_ROLES`` the scope tests sync: ``regional`` holds
products under ``tree:region``.

Used with ``override_settings(ROOT_URLCONF=__name__, KARNI_API_ROUTER=
"tests.taxonomy.urls.get_router")``. Nothing here is autodiscovered.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q
from django.urls import include, path

from karni.api import Access, Authenticated, BaseViewSet, Granted, HasRole, Public, Where
from karni.api.routers import KarniRouter
from tests.taxoapp.models import Category, Product, Region, Supplier

ROLES = {
    "regional": {
        "grants": {
            "taxoapp.product:view": "tree:region",
            "taxoapp.region:view": "all",
        }
    },
}


def _not_secret(request: Any) -> Q:
    return ~Q(name__startswith="Secret")


def _not_hidden(request: Any) -> Q:
    return ~Q(code="hidden")


class ProductViewSet(BaseViewSet):
    model = Product
    access = Access(read=Where(_not_secret) | HasRole("staff"), write=Authenticated())
    search_fields = ["name"]
    auto_register = False


class RegionViewSet(BaseViewSet):
    model = Region
    access = Access(read=Where(_not_hidden), write=Authenticated())
    auto_register = False


class CategoryViewSet(BaseViewSet):
    model = Category
    access = Access(read=Public(), write=Authenticated())
    auto_register = False


class SupplierViewSet(BaseViewSet):
    model = Supplier
    access = Access(read=Public(), write=Authenticated())
    auto_register = False


class GrantedProductViewSet(BaseViewSet):
    model = Product
    access = Granted()
    auto_register = False


router = KarniRouter()
router.register("products", ProductViewSet, basename="tx-products")
router.register("regions", RegionViewSet, basename="tx-regions")
router.register("categories", CategoryViewSet, basename="tx-categories")
router.register("suppliers", SupplierViewSet, basename="tx-suppliers")

#: The tree scope's resources (``tests/taxonomy/test_scope.py``): products by grant.
scope_router = KarniRouter()
scope_router.register("products", GrantedProductViewSet, basename="tx-granted-products")
scope_router.register("regions", RegionViewSet, basename="tx-scope-regions")


def get_router() -> KarniRouter:
    return router


def get_scope_router() -> KarniRouter:
    return scope_router


urlpatterns = [path("api/", include(router.urls)), path("scoped/", include(scope_router.urls))]
