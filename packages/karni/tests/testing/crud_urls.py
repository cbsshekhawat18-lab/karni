"""A router of well- and badly-behaved viewsets for the assert_crud / assert_isolated suites.

Used with ``override_settings(ROOT_URLCONF=__name__, KARNI_API_ROUTER=
"tests.testing.crud_urls.get_router")`` so the project-wide schema snapshot
never sees these routes (none of them sits in an autodiscovered module).
"""

from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.db.models import QuerySet
from django.urls import include, path
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import BasePermission

from karni.api import Access, Authenticated, BaseViewSet, Granted, HasRole, Owned, Public
from karni.api.routers import KarniRouter
from karni.pagination import KarniPageNumberPagination
from tests.testapp.models import Event, Venue


class EventViewSet(BaseViewSet):
    """Organizers create; owners read and write their own rows; staff read everything."""

    model = Event
    access = Access(
        read=Owned("organizer") | HasRole("staff"),
        write=Owned("organizer"),
        create=HasRole("organizer"),
    )
    search_fields = ("title",)


class GrantedEventViewSet(BaseViewSet):
    """Whatever the roles grant (P2): the isolation suite syncs own/related grants."""

    model = Event
    access = Granted()
    search_fields = ("title",)


class VenueViewSet(BaseViewSet):
    """Everyone signed in reads; only staff write."""

    model = Venue
    access = Access(read=Authenticated(), write=HasRole("staff"))


class StaffVenueViewSet(BaseViewSet):
    model = Venue
    access = Access(read=HasRole("staff"), write=HasRole("staff"))


class PublicVenueViewSet(BaseViewSet):
    model = Venue
    access = Access(read=Public(), write=Authenticated())


# misbehaving viewsets


class AllowAll(BasePermission):
    def has_permission(self, request: Any, view: Any) -> bool:
        return True


class NoGateEventViewSet(EventViewSet):
    """Declares Owned/HasRole but replaces the gate: anyone gets through."""

    def get_permissions(self) -> list[BasePermission]:
        return [AllowAll()]


class IgnoresPageSize(KarniPageNumberPagination):
    def get_page_size(self, request: Any) -> int:
        return 50


class BrokenPaginationEventViewSet(EventViewSet):
    pagination_class = IgnoresPageSize


class IgnoringFilterBackend(DjangoFilterBackend):
    def filter_queryset(self, request: Any, queryset: QuerySet[Any], view: Any) -> QuerySet[Any]:
        return queryset


class BrokenFilteringEventViewSet(EventViewSet):
    filter_backends = [IgnoringFilterBackend, OrderingFilter]


class LoudVenueSerializer(serializers.ModelSerializer):
    class Meta:
        model = Venue
        fields = ["id", "name", "city"]

    def to_representation(self, instance: Venue) -> dict[str, Any]:
        data = dict(super().to_representation(instance))
        data["undocumented"] = True
        return data


class UndocumentedFieldVenueViewSet(VenueViewSet):
    serializer_class = LoudVenueSerializer


class NoStampEventViewSet(EventViewSet):
    def perform_create(self, serializer: Any) -> None:
        serializer.save()


class OwnerInBodySerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ["id", "title", "starts_at", "organizer"]


class OwnerFromBodyEventViewSet(EventViewSet):
    """Lets the request body pick the owner (and never stamps it)."""

    serializer_class = OwnerInBodySerializer

    def perform_create(self, serializer: Any) -> None:
        serializer.save()


class UndeclaredEventViewSet(BaseViewSet):
    model = Event


class LeakyEventViewSet(EventViewSet):
    """Bypasses its own read scope: every row is everyone's."""

    def read_scope(self, queryset: QuerySet[Any]) -> tuple[QuerySet[Any], bool]:
        return queryset, False


ROUTES = {
    "events": EventViewSet,
    "granted-events": GrantedEventViewSet,
    "venues": VenueViewSet,
    "public-venues": PublicVenueViewSet,
    "staff-venues": StaffVenueViewSet,
    "no-gate-events": NoGateEventViewSet,
    "broken-pagination-events": BrokenPaginationEventViewSet,
    "broken-filtering-events": BrokenFilteringEventViewSet,
    "undocumented-venues": UndocumentedFieldVenueViewSet,
    "no-stamp-events": NoStampEventViewSet,
    "owner-from-body-events": OwnerFromBodyEventViewSet,
    "undeclared-events": UndeclaredEventViewSet,
    "leaky-events": LeakyEventViewSet,
}

router = KarniRouter()
for prefix, viewset in ROUTES.items():
    router.register(prefix, viewset, basename=f"crud-{prefix}")


def get_router() -> KarniRouter:
    return router


urlpatterns = [path("admin/", admin.site.urls), path("api/", include(router.urls))]
