"""Full CRUD from the bare ``EventViewSet`` declaration, through real routes.

Everything here runs against the URLs the auto-router registered (mounted at
``api/`` by ``tests/urls.py``) — no hand-written serializer, filterset or
route exists for the test app.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from tests.testapp.models import Event, Tag, Venue

pytestmark = pytest.mark.django_db

LIST_URL = "testapp-event-list"
DETAIL_URL = "testapp-event-detail"
STARTS_AT = "2030-05-01T18:00:00Z"


@pytest.fixture(autouse=True)
def _reset_throttle_state() -> Any:
    """Keep DRF's default anon/user throttles from leaking across tests."""
    yield
    cache.clear()


@pytest.fixture
def user() -> Any:
    return get_user_model().objects.create_user(
        email="crud@example.com", password="a-strong-password-123"
    )


@pytest.fixture
def client(user: Any) -> APIClient:
    api_client = APIClient()
    api_client.force_authenticate(user=user)
    return api_client


def _event(title: str = "Event", **kwargs: Any) -> Event:
    kwargs.setdefault("starts_at", timezone.now())
    return Event.objects.create(title=title, **kwargs)


def _detail_url(event_id: Any) -> str:
    return reverse(DETAIL_URL, kwargs={"pk": str(event_id)})


def test_list_returns_paginated_events(client: APIClient) -> None:
    first = _event("First")
    second = _event("Second")
    response = client.get(reverse(LIST_URL))
    assert response.status_code == 200
    assert response.data["count"] == 2
    assert {row["id"] for row in response.data["results"]} == {str(first.pk), str(second.pk)}


def test_retrieve_serializes_every_api_field(client: APIClient) -> None:
    venue = Venue.objects.create(name="Arena", city="Berlin")
    event = _event("Show", description="Loud.", capacity=100, venue=venue)
    response = client.get(_detail_url(event.pk))
    assert response.status_code == 200
    data = response.data
    assert data["id"] == str(event.pk)
    assert data["title"] == "Show"
    assert data["description"] == "Loud."
    assert data["capacity"] == 100
    assert data["status"] == Event.Status.DRAFT
    assert data["is_public"] is True
    # Unexpanded relations are PKs (raw UUIDs in response.data; JSON renders
    # them as strings).
    assert data["venue"] == venue.pk
    assert data["organizer"] is None
    assert data["tags"] == []
    assert data["created_at"] is not None
    assert data["updated_at"] is not None


def test_create_from_bare_declaration(client: APIClient) -> None:
    venue = Venue.objects.create(name="Arena", city="Berlin")
    tag = Tag.objects.create(name="music")
    response = client.post(
        reverse(LIST_URL),
        {
            "title": "Launch",
            "starts_at": STARTS_AT,
            "capacity": 20,
            "venue": str(venue.pk),
            "tags": [str(tag.pk)],  # M2M is writable by default (B10)
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    event = Event.objects.get(pk=response.data["id"])
    assert event.title == "Launch"
    assert event.venue == venue
    assert list(event.tags.all()) == [tag]
    assert response.data["created_at"] is not None


def test_create_requires_authentication() -> None:
    response = APIClient().post(
        reverse(LIST_URL), {"title": "Nope", "starts_at": STARTS_AT}, format="json"
    )
    assert response.status_code in (401, 403)
    assert Event.objects.count() == 0


def test_create_ignores_read_only_id_created_at_and_status(client: APIClient) -> None:
    forged_id = str(uuid.uuid4())
    response = client.post(
        reverse(LIST_URL),
        {
            "title": "Forged",
            "starts_at": STARTS_AT,
            "id": forged_id,
            "created_at": "1999-01-01T00:00:00Z",
            "status": Event.Status.PUBLISHED,  # APIMeta.read_only
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["id"] != forged_id
    assert response.data["status"] == Event.Status.DRAFT
    event = Event.objects.get(pk=response.data["id"])
    assert event.status == Event.Status.DRAFT
    assert event.created_at.year != 1999


def test_write_only_internal_note_is_stored_but_never_read_back(client: APIClient) -> None:
    response = client.post(
        reverse(LIST_URL),
        {"title": "Noted", "starts_at": STARTS_AT, "internal_note": "vip list"},
        format="json",
    )
    assert response.status_code == 201, response.data
    assert "internal_note" not in response.data
    event = Event.objects.get(pk=response.data["id"])
    assert event.internal_note == "vip list"
    detail = client.get(_detail_url(event.pk))
    assert "internal_note" not in detail.data


def test_full_update_via_put(client: APIClient) -> None:
    event = _event("Before", capacity=10)
    response = client.put(
        _detail_url(event.pk),
        {"title": "After", "starts_at": STARTS_AT, "is_public": False},
        format="json",
    )
    assert response.status_code == 200, response.data
    event.refresh_from_db()
    assert event.title == "After"
    assert event.is_public is False
    # DRF semantics: fields omitted from a PUT that are not required are
    # simply not written — they keep their stored value.
    assert event.capacity == 10


def test_partial_update_via_patch(client: APIClient) -> None:
    event = _event("Before", capacity=10)
    response = client.patch(_detail_url(event.pk), {"title": "After"}, format="json")
    assert response.status_code == 200, response.data
    event.refresh_from_db()
    assert event.title == "After"
    assert event.capacity == 10  # untouched by PATCH


def test_patch_cannot_move_read_only_fields(client: APIClient) -> None:
    event = _event("Pinned")
    original_created = event.created_at
    response = client.patch(
        _detail_url(event.pk),
        {
            "id": str(uuid.uuid4()),
            "created_at": "1999-01-01T00:00:00Z",
            "status": Event.Status.PUBLISHED,
        },
        format="json",
    )
    assert response.status_code == 200, response.data
    event.refresh_from_db()
    assert event.created_at == original_created
    assert event.status == Event.Status.DRAFT
    assert response.data["id"] == str(event.pk)


def test_delete(client: APIClient) -> None:
    event = _event("Doomed")
    response = client.delete(_detail_url(event.pk))
    assert response.status_code == 204
    assert not Event.objects.filter(pk=event.pk).exists()


def test_validation_errors_are_400(client: APIClient) -> None:
    response = client.post(reverse(LIST_URL), {"starts_at": STARTS_AT}, format="json")
    assert response.status_code == 400
    assert "title" in response.data
