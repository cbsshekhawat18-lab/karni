"""The tree scope (``tree:<path>``, experimental): resources and roles for ``tests/treescope/``.

The trees are the test app's: ``Category`` (ordered) and ``Region``.
``Product`` points at a category (a foreign key) and at regions (a
many-to-many), and ``Listing`` reaches both through its product.

* ``products`` — ``Granted()``, with a custom ``card/`` action;
* ``listings`` — ``Granted()``: ``tree:product__category`` goes through a relation;
* ``where-products`` — ``Where(tree_scope(Product, "category"))``;
* ``categories`` and ``regions`` — ``Granted()``: the tree endpoints and ``access/``.

``ROLES`` is the ``KARNI_ROLES`` the suite syncs. ``buyer`` holds products
under ``tree:category``, listings under ``tree:product__category`` and reads
every category and region. ``regional`` holds products under
``tree:regions``. A role's node is ``user.<path>`` (``user.category``), and a
user grant's nodes are its targets.

Used with ``override_settings(ROOT_URLCONF=__name__, KARNI_API_ROUTER=
"tests.treescope.get_router")``. Nothing here is autodiscovered.
"""

from __future__ import annotations

from typing import Any

from django.urls import include, path
from rest_framework.decorators import action
from rest_framework.response import Response

from karni.accounts.tree_scope import tree_scope
from karni.api import Access, BaseViewSet, Granted, HasRole, Where
from karni.api.routers import KarniRouter
from tests.testapp.models import Category, Listing, Product, Region

PRODUCT_VIEW = "testapp.product:view"
LISTING_VIEW = "testapp.listing:view"

ROLES = {
    "buyer": {
        "grants": {
            PRODUCT_VIEW: "tree:category",
            "testapp.product:change": "tree:category",
            LISTING_VIEW: "tree:product__category",
            "testapp.listing:add": "all",
            "testapp.listing:change": "tree:product__category",
            "testapp.category:view": "all",
            "testapp.region:view": "all",
        }
    },
    "regional": {"grants": {PRODUCT_VIEW: "tree:regions"}},
    "ops": {"system": True, "grants": {"*": "all"}},
}


class ScopedProductViewSet(BaseViewSet):
    model = Product
    access = Granted()
    auto_register = False

    @action(detail=True, methods=["get"], url_path="card")
    def card(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """A custom read action: the row comes through the read scope."""
        return Response({"name": self.get_object().name})


class ScopedListingViewSet(BaseViewSet):
    model = Listing
    access = Granted()
    auto_register = False


class WhereProductViewSet(BaseViewSet):
    model = Product
    access = Access(
        read=Where(tree_scope(Product, "category", permission=PRODUCT_VIEW)),
        write=HasRole("staff"),
    )
    auto_register = False


class ForestCategoryViewSet(BaseViewSet):
    model = Category
    access = Granted()
    auto_register = False


class ForestRegionViewSet(BaseViewSet):
    model = Region
    access = Granted()
    auto_register = False


router = KarniRouter()
router.register("products", ScopedProductViewSet, basename="ts-products")
router.register("listings", ScopedListingViewSet, basename="ts-listings")
router.register("where-products", WhereProductViewSet, basename="ts-where-products")
router.register("categories", ForestCategoryViewSet, basename="ts-categories")
router.register("regions", ForestRegionViewSet, basename="ts-regions")


def get_router() -> KarniRouter:
    return router


urlpatterns = [path("api/", include(router.urls))]
