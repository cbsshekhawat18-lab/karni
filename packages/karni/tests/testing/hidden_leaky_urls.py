"""The hidden-row router plus viewsets that leak the hidden row, each through one surface.

``assert_row_hidden`` must name every one of these leaks (``tests/testing/test_hidden.py``).
The well-behaved resources are registered first, so they stay the read scope
of their models (``viewset_for_model`` takes the first registration).
"""

from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.db.models import QuerySet
from django.http import Http404
from django.urls import include, path
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from karni.api.routers import KarniRouter
from karni.pagination import KarniPageNumberPagination
from tests.testapp.models import Event, Venue
from tests.testing.hidden_urls import ROUTES, HiddenEventViewSet


class LeakyEventViewSet(HiddenEventViewSet):
    """Bypasses its read scope: every event is everyone's."""

    def read_scope(self, queryset: QuerySet[Any]) -> tuple[QuerySet[Any], bool]:
        return queryset, False


class ForbiddingEventViewSet(HiddenEventViewSet):
    """Looks rows up unscoped, then refuses the out-of-scope ones with a 403."""

    def get_object(self) -> Any:
        found = Event.objects.filter(pk=self.kwargs["pk"]).first()
        if found is None:
            raise Http404
        if not self.get_queryset().filter(pk=found.pk).exists():
            raise PermissionDenied("Not your event.")
        return found


class _PlainVenueSerializer(serializers.ModelSerializer):
    class Meta:
        model = Venue
        fields = ["id", "name", "city"]


class _InliningEventSerializer(serializers.ModelSerializer):
    venue = _PlainVenueSerializer(read_only=True)

    class Meta:
        model = Event
        fields = ["id", "title", "starts_at", "venue"]


class InliningEventViewSet(HiddenEventViewSet):
    """A hand-written serializer that always nests the venue, readable or not."""

    serializer_class = _InliningEventSerializer


class TagOrderedEventViewSet(HiddenEventViewSet):
    """Declares a to-many relation orderable: one row per tag."""

    ordering_fields = ["title", "tags"]


class _OvercountingPagination(KarniPageNumberPagination):
    def get_paginated_response(self, data: Any) -> Any:
        response = super().get_paginated_response(data)
        response.data["count"] = Event._base_manager.count()
        return response


class OvercountingEventViewSet(HiddenEventViewSet):
    """Counts every event, not the client's."""

    pagination_class = _OvercountingPagination


class ExportLeakEventViewSet(HiddenEventViewSet):
    """Exports every event, not the client's."""

    def filter_queryset(self, queryset: QuerySet[Any]) -> QuerySet[Any]:
        if getattr(self, "action", None) == "export":
            return Event.objects.all()
        filtered: QuerySet[Any] = super().filter_queryset(queryset)
        return filtered


LEAKY_ROUTES = {
    "leaky-events": LeakyEventViewSet,
    "forbidding-events": ForbiddingEventViewSet,
    "inlining-events": InliningEventViewSet,
    "tag-ordered-events": TagOrderedEventViewSet,
    "overcounting-events": OvercountingEventViewSet,
    "export-leak-events": ExportLeakEventViewSet,
}

router = KarniRouter()
for prefix, viewset in {**ROUTES, **LEAKY_ROUTES}.items():
    router.register(prefix, viewset, basename=f"hidden-{prefix}")


def get_router() -> KarniRouter:
    return router


urlpatterns = [path("admin/", admin.site.urls), path("api/", include(router.urls))]
