"""The people API's own router and URLconf, as a project with ``KARNI_PEOPLE_API`` routes them.

The core suite sets ``KARNI_PEOPLE_API = False`` so the test app's OpenAPI
snapshot stays as it is; these tests use ``ROOT_URLCONF="tests.people.urls"``
and ``KARNI_API_ROUTER="tests.people.urls.get_router"``.
"""

from __future__ import annotations

from django.conf import settings
from django.urls import include, path
from django.utils.module_loading import import_string

from karni.api.global_search import GlobalSearchView
from karni.api.routers import KarniRouter
from karni.people.viewsets import (
    AddressViewSet,
    MembershipViewSet,
    OrganisationViewSet,
    PersonViewSet,
)


def get_router() -> KarniRouter:
    """The people resources, registered as autodiscovery would name them."""
    router = KarniRouter()
    router.register("people", PersonViewSet, basename="people-person")
    router.register("organisations", OrganisationViewSet, basename="people-organisation")
    router.register("people-memberships", MembershipViewSet, basename="people-membership")
    router.register("people-addresses", AddressViewSet, basename="people-address")
    return router


urlpatterns = [
    path("admin/", import_string(settings.KARNI_ADMIN_SITE).urls),
    path("api/auth/", include("karni.accounts.urls")),
    path("api/search/", GlobalSearchView.as_view(), name="people-search"),
    path("api/", include(get_router().urls)),
]
