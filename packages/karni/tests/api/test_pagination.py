"""Pagination defaults (conf-driven) as seen through a bare BaseViewSet."""

from __future__ import annotations

from typing import Any

import pytest
from django.conf import settings as django_settings
from django.core.cache import cache
from django.utils import timezone
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from karni.pagination import KarniPageNumberPagination
from tests.testapp.models import Event
from tests.testapp.viewsets import EventViewSet


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


def test_page_size_capped_at_max_page_size() -> None:
    pagination = KarniPageNumberPagination()
    request = Request(APIRequestFactory().get("/", {"page_size": "100000"}))
    assert pagination.get_page_size(request) == pagination.max_page_size == 500
