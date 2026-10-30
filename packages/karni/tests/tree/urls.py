"""Tree resources with narrowed access, for ``tests/tree/test_api.py``.

* ``regions`` — every region but the ones coded ``secret`` is readable, and
  signed-in users may change every region but the ones coded ``locked``;
* ``small-regions`` — every region, at most 4 nodes per ``tree/`` answer;
* ``categories`` — the ordered tree, changed by staff only.

Used with ``override_settings(ROOT_URLCONF=__name__, KARNI_API_ROUTER=
"tests.tree.urls.get_router")``. Nothing here is autodiscovered.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q
from django.urls import include, path

from karni.api import Access, Authenticated, BaseViewSet, HasRole, Public, Where
from karni.api.routers import KarniRouter
from tests.testapp.models import Category, Region


def _not_secret(request: Any) -> Q:
    return ~Q(code="secret")


def _not_locked(request: Any) -> Q:
    return ~Q(code="locked")


class ScopedRegionViewSet(BaseViewSet):
    model = Region
    access = Access(read=Where(_not_secret), write=Authenticated() & Where(_not_locked))
    auto_register = False


class SmallRegionViewSet(BaseViewSet):
    model = Region
    access = Access(read=Public(), write=Authenticated())
    tree_max_nodes = 4
    auto_register = False


class StaffCategoryViewSet(BaseViewSet):
    model = Category
    access = Access(read=Authenticated(), write=HasRole("staff"))
    auto_register = False


router = KarniRouter()
router.register("regions", ScopedRegionViewSet, basename="tree-regions")
router.register("small-regions", SmallRegionViewSet, basename="tree-small-regions")
router.register("categories", StaffCategoryViewSet, basename="tree-categories")


def get_router() -> KarniRouter:
    return router


urlpatterns = [path("api/", include(router.urls))]
