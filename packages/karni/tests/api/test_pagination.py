"""Pagination defaults (conf-driven) as seen through a bare BaseViewSet."""

from __future__ import annotations

from typing import Any, cast

import pytest
from django.conf import settings as django_settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test.utils import override_settings
from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from karni.api import Access, Authenticated, BaseViewSet, Public, Unpaginated
from karni.pagination import KarniCursorPagination, KarniPageNumberPagination
from tests.testapp.models import Event
from tests.testapp.viewsets import EventViewSet

OPEN = Access(read=Public(), write=Authenticated())


@pytest.fixture(autouse=True)
def _reset_throttle_state() -> Any:
    yield
    cache.clear()


def _status_value() -> str:
    return list(Event._meta.get_field("status").choices)[0][0]


def _bulk_events(count: int) -> None:
    now = timezone.now()
    status = _status_value()
    Event.objects.bulk_create(
        Event(title=f"Event {index}", starts_at=now, status=status) for index in range(count)
    )


def test_conf_default_page_size_is_50() -> None:
    assert django_settings.REST_FRAMEWORK["PAGE_SIZE"] == 50


def test_viewset_uses_karni_pagination_class() -> None:
    assert issubclass(EventViewSet.pagination_class, KarniPageNumberPagination)


@pytest.mark.django_db
def test_default_page_size_applied() -> None:
    _bulk_events(55)
    response = EventViewSet.as_view({"get": "list"})(APIRequestFactory().get("/"))
    assert response.status_code == 200
    assert response.data["count"] == 55
    assert len(response.data["results"]) == 50
    assert response.data["next"] is not None
    assert response.data["previous"] is None


@pytest.mark.django_db
def test_page_size_query_parameter() -> None:
    _bulk_events(7)
    response = EventViewSet.as_view({"get": "list"})(
        APIRequestFactory().get("/", {"page_size": "3"})
    )
    assert response.status_code == 200
    assert len(response.data["results"]) == 3
    assert response.data["count"] == 7


@pytest.mark.django_db
def test_second_page() -> None:
    _bulk_events(55)
    response = EventViewSet.as_view({"get": "list"})(
        APIRequestFactory().get("/", {"page": "2", "page_size": "30"})
    )
    assert response.status_code == 200
    assert len(response.data["results"]) == 25
    assert response.data["previous"] is not None
    assert response.data["next"] is None


def test_page_size_capped_at_karni_max_page_size() -> None:
    pagination = KarniPageNumberPagination()
    request = Request(APIRequestFactory().get("/", {"page_size": "100000"}))
    assert pagination.get_page_size(request) == pagination.get_max_page_size() == 100


# --- the hard cap and its floor (ADR 0001 Q3.4) -------------------------------------------


def test_cap_follows_the_setting() -> None:
    pagination = KarniPageNumberPagination()
    request = Request(APIRequestFactory().get("/", {"page_size": "1000"}))
    with override_settings(KARNI_MAX_PAGE_SIZE=40):
        assert pagination.get_page_size(request) == 40


def test_a_subclass_may_lower_the_cap_never_raise_it() -> None:
    class Small(KarniPageNumberPagination):
        max_page_size = 10

    class Huge(KarniPageNumberPagination):
        max_page_size = 10_000

    request = Request(APIRequestFactory().get("/", {"page_size": "1000"}))
    assert Small().get_page_size(request) == 10
    assert Huge().get_page_size(request) == 100


def test_default_page_size_is_capped_too() -> None:
    request = Request(APIRequestFactory().get("/"))
    with override_settings(KARNI_MAX_PAGE_SIZE=30):
        assert KarniPageNumberPagination().get_page_size(request) == 30


@pytest.mark.parametrize("raw", ["0", "-5", "lots"])
def test_bad_page_size_falls_back_to_the_default(raw: str) -> None:
    request = Request(APIRequestFactory().get("/", {"page_size": raw}))
    assert KarniPageNumberPagination().get_page_size(request) == 50


@pytest.mark.django_db
def test_cursor_pagination() -> None:
    class CursorEvents(EventViewSet):
        pagination_class = KarniCursorPagination
        auto_register = False

    _bulk_events(7)
    response = CursorEvents.as_view({"get": "list"})(
        APIRequestFactory().get("/", {"page_size": "5"})
    )
    assert response.status_code == 200
    assert len(response.data["results"]) == 5
    assert "count" not in response.data and response.data["next"]


# --- switching pagination off (ADR 0001 Q3.5) ---------------------------------------------------


def test_pagination_class_none_is_a_class_definition_error() -> None:
    with pytest.raises(ImproperlyConfigured, match=r"Unpaginated\(max_rows=N"):

        class Everything(BaseViewSet):
            model = Event
            access = OPEN
            pagination_class = None
            auto_register = False


def test_a_non_karni_paginator_is_refused() -> None:
    with pytest.raises(ImproperlyConfigured, match="KarniPagination"):

        class Stock(BaseViewSet):
            model = Event
            access = OPEN
            pagination_class = PageNumberPagination
            auto_register = False


def test_unpaginated_needs_a_limit_and_a_reason() -> None:
    with pytest.raises(ImproperlyConfigured, match="positive row limit"):
        Unpaginated(max_rows=0, reason="export")
    with pytest.raises(ImproperlyConfigured, match="reason"):
        Unpaginated(max_rows=10, reason=" ")
    with pytest.raises(ImproperlyConfigured, match="must be Unpaginated"):

        class Wrong(BaseViewSet):
            model = Event
            access = OPEN
            pagination = 500  # type: ignore[assignment]
            auto_register = False

    with pytest.raises(ImproperlyConfigured, match="keep one"):

        class Both(BaseViewSet):
            model = Event
            access = OPEN
            pagination = Unpaginated(max_rows=5, reason="tiny lookup table")
            pagination_class = KarniCursorPagination
            auto_register = False


class ExportViewSet(BaseViewSet):
    model = Event
    access = OPEN
    pagination_class = None  # allowed: the declaration below says why
    pagination = Unpaginated(max_rows=5, reason="CSV export of a short list")
    auto_register = False


@pytest.mark.django_db
def test_unpaginated_returns_a_plain_list_sliced_at_max_rows() -> None:
    _bulk_events(4)
    response = ExportViewSet.as_view({"get": "list"})(APIRequestFactory().get("/"))
    assert isinstance(response.data, list) and len(response.data) == 4
    assert "X-Karni-Truncated" not in response
    _bulk_events(3)
    response = ExportViewSet.as_view({"get": "list"})(APIRequestFactory().get("/"))
    assert len(response.data) == 5
    assert response["X-Karni-Truncated"] == "true"


def test_unpaginated_schema_is_a_plain_array() -> None:
    paginator = cast(Any, ExportViewSet).pagination_class()
    schema = {"type": "array", "items": {"$ref": "#/components/schemas/Event"}}
    assert paginator.get_paginated_response_schema(schema) is schema
    assert paginator.get_schema_operation_parameters(ExportViewSet()) == []


@pytest.mark.django_db
def test_a_missing_paginator_is_refused_at_request_time() -> None:
    class Lost(BaseViewSet):
        model = Event
        access = OPEN
        auto_register = False

    Lost.pagination_class = None  # what a REST_FRAMEWORK without a default does
    with pytest.raises(ImproperlyConfigured, match="has no pagination_class"):
        Lost.as_view({"get": "list"})(APIRequestFactory().get("/"))


# --- list-returning custom actions (ADR 0001 Q3.6) ----------------------------------------------


class ArchiveViewSet(BaseViewSet):
    model = Event
    access = OPEN
    auto_register = False

    @action(detail=False)
    def published(self, request: Any) -> Any:
        return self.paginated_response(self.get_queryset().filter(status="published"))


@pytest.mark.django_db
def test_paginated_response_gives_the_list_envelope_and_optimises() -> None:
    from karni.performance import record_queries
    from tests.testapp.models import Tag

    tag = Tag.objects.create(name="t")
    now = timezone.now()
    for index in range(12):
        Event.objects.create(title=f"E{index}", starts_at=now, status="published").tags.add(tag)
    view = ArchiveViewSet.as_view({"get": "published"})
    with record_queries() as recorder:
        response = view(APIRequestFactory().get("/", {"page_size": "10"}))
    assert response.status_code == 200
    assert response.data["count"] == 12 and len(response.data["results"]) == 10
    assert recorder.count == 3  # COUNT, events, tags prefetch (not one per row)
