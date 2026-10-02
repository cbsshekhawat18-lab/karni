"""``?expand=`` behaviour: nesting, guards, aliasing and query optimisation."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework import serializers
from rest_framework.relations import PrimaryKeyRelatedField
from rest_framework.test import APIRequestFactory

from karni.api.serializers import build_serializer
from tests.testapp.models import Event, Tag, Venue
from tests.testapp.viewsets import EventViewSet, VenueViewSet

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset_throttle_state() -> Any:
    yield
    cache.clear()


@pytest.fixture
def organizer() -> Any:
    return get_user_model().objects.create_user(
        email="organizer@example.com", password="a-strong-password-123"
    )


@pytest.fixture
def venue() -> Venue:
    return Venue.objects.create(name="Arena", city="Berlin")


def _event(title: str = "Event", **kwargs: Any) -> Event:
    kwargs.setdefault("starts_at", timezone.now())
    return Event.objects.create(title=title, **kwargs)


def _list(query: dict[str, Any] | None = None, viewset: type[Any] = EventViewSet) -> Any:
    view = viewset.as_view({"get": "list"})
    return view(APIRequestFactory().get("/", query or {}))


def _retrieve(pk: Any, query: dict[str, Any] | None = None) -> Any:
    view = EventViewSet.as_view({"get": "retrieve"})
    return view(APIRequestFactory().get("/", query or {}), pk=str(pk))


def _only_row(response: Any) -> dict[str, Any]:
    assert response.status_code == 200, response.data
    assert response.data["count"] == 1
    return response.data["results"][0]


# --- nesting -------------------------------------------------------------------


def test_unexpanded_relations_are_primary_keys(organizer: Any, venue: Venue) -> None:
    tag = Tag.objects.create(name="music")
    event = _event(organizer=organizer, venue=venue)
    event.tags.add(tag)
    row = _only_row(_list())
    # PrimaryKeyRelatedField hands back the raw pk (a UUID here); the JSON
    # renderer is what turns it into a string on the wire.
    assert row["venue"] == venue.pk
    assert row["organizer"] == organizer.pk
    assert row["tags"] == [tag.pk]


def test_expand_venue_nests_the_object(organizer: Any, venue: Venue) -> None:
    _event(organizer=organizer, venue=venue)
    row = _only_row(_list({"expand": "venue"}))
    assert row["venue"] == {
        "id": str(venue.pk),
        "name": "Arena",
        "city": "Berlin",
        "created_at": row["venue"]["created_at"],
        "updated_at": row["venue"]["updated_at"],
    }
    # Only the requested relation nests; the rest stay PKs.
    assert row["organizer"] == organizer.pk


def test_expand_organizer_nests_the_api_meta_surface(organizer: Any) -> None:
    _event(organizer=organizer)
    row = _only_row(_list({"expand": "organizer"}))
    nested = row["organizer"]
    assert nested["id"] == str(organizer.pk)
    assert nested["email"] == "organizer@example.com"
    assert "password" not in nested
    assert "is_superuser" not in nested


def test_expand_tags_nests_a_list(venue: Venue) -> None:
    event = _event(venue=venue)
    event.tags.add(Tag.objects.create(name="music"), Tag.objects.create(name="live"))
    row = _only_row(_list({"expand": "tags"}))
    assert {tag["name"] for tag in row["tags"]} == {"music", "live"}


def test_expand_works_on_retrieve(venue: Venue) -> None:
    event = _event(venue=venue)
    response = _retrieve(event.pk, {"expand": "venue"})
    assert response.status_code == 200
    assert response.data["venue"]["city"] == "Berlin"


def test_comma_list_and_repeated_params_are_merged(organizer: Any, venue: Venue) -> None:
    _event(organizer=organizer, venue=venue)
    comma = _only_row(_list({"expand": "venue,organizer"}))
    repeated = _only_row(_list({"expand": ["venue", "organizer"]}))
    for row in (comma, repeated):
        assert row["venue"]["name"] == "Arena"
        assert row["organizer"]["email"] == "organizer@example.com"


def test_dotted_path_validates_but_api_meta_still_wins(organizer: Any) -> None:
    """``organizer.groups`` is a legal path, yet the user model's APIMeta

    excludes ``groups`` — expansion never leaks a field back in (B5).
    """
    _event(organizer=organizer)
    row = _only_row(_list({"expand": "organizer.groups"}))
    assert row["organizer"]["email"] == "organizer@example.com"
    assert "groups" not in row["organizer"]


# --- guards ----------------------------------------------------------------------


def test_unknown_expand_key_is_400_listing_allowed_keys() -> None:
    response = _list({"expand": "nope"})
    assert response.status_code == 400
    message = str(response.data["expand"])
    assert "nope" in message
    for key in ("organizer", "tags", "venue"):
        assert key in message


def test_unknown_nested_key_is_400_listing_that_level(organizer: Any) -> None:
    response = _list({"expand": "organizer.nope"})
    assert response.status_code == 400
    message = str(response.data["expand"])
    assert "groups" in message  # User's own expandable relations, not Event's
    assert "venue" not in message


def test_path_deeper_than_max_depth_is_400() -> None:
    # KARNI_API_MAX_EXPAND_DEPTH defaults to 2; three segments must fail.
    response = _list({"expand": "organizer.groups.permissions"})
    assert response.status_code == 400
    assert "depth" in str(response.data["expand"]).lower()


def test_viewset_expand_depth_overrides_the_setting(organizer: Any) -> None:
    class ShallowEventViewSet(EventViewSet):
        expand_depth = 1

    _event(organizer=organizer)
    denied = _list({"expand": "organizer.groups"}, viewset=ShallowEventViewSet)
    assert denied.status_code == 400
    allowed = _list({"expand": "organizer"}, viewset=ShallowEventViewSet)
    assert allowed.status_code == 200


def test_cycle_stops_at_the_primary_key() -> None:
    # Building Event's serializer while Venue is already on the nesting path
    # simulates a Venue → Event → Venue cycle: the guard keeps the PK field.
    serializer_class = build_serializer(Event, expand=frozenset({"venue"}), _seen=(Venue,))
    field = serializer_class().fields["venue"]
    assert isinstance(field, PrimaryKeyRelatedField)
    assert not isinstance(field, serializers.BaseSerializer)


# --- expandable_fields (restriction, aliasing, reverse relations) ---------------


def test_expandable_fields_restricts_the_allowed_keys(venue: Venue) -> None:
    class VenueOnlyEventViewSet(EventViewSet):
        expandable_fields = {"venue": "venue"}

    _event(venue=venue)
    ok = _list({"expand": "venue"}, viewset=VenueOnlyEventViewSet)
    assert ok.status_code == 200
    denied = _list({"expand": "organizer"}, viewset=VenueOnlyEventViewSet)
    assert denied.status_code == 400
    assert "venue" in str(denied.data["expand"])


def test_expandable_fields_aliases_resolve_to_the_relation(venue: Venue) -> None:
    class AliasedEventViewSet(EventViewSet):
        expandable_fields = {"where": "venue"}

    _event(venue=venue)
    row = _only_row(_list({"expand": "where"}, viewset=AliasedEventViewSet))
    assert row["venue"]["name"] == "Arena"  # nested under the relation name
    denied = _list({"expand": "venue"}, viewset=AliasedEventViewSet)
    assert denied.status_code == 400  # only the alias is a valid key


def test_reverse_relation_expandable_only_when_listed(venue: Venue) -> None:
    _event("On the books", venue=venue)

    denied = _list({"expand": "events"}, viewset=VenueViewSet)
    assert denied.status_code == 400  # reverse relations are never automatic

    class VenueWithEventsViewSet(VenueViewSet):
        expandable_fields = {"events": "events"}

    row = _only_row(_list({"expand": "events"}, viewset=VenueWithEventsViewSet))
    assert [event["title"] for event in row["events"]] == ["On the books"]


# --- query optimisation ----------------------------------------------------------


def test_expansion_uses_select_related_and_prefetch(
    organizer: Any, venue: Venue, django_assert_num_queries: Any
) -> None:
    tags = [Tag.objects.create(name=f"tag-{index}") for index in range(2)]
    for index in range(3):
        event = _event(f"Event {index}", organizer=organizer, venue=venue)
        event.tags.add(*tags)

    view = EventViewSet.as_view({"get": "list"})
    request = APIRequestFactory().get("/", {"expand": "venue,organizer,tags"})
    # Exactly three queries, independent of row count:
    #   1. COUNT(*) for pagination,
    #   2. SELECT events JOIN venue JOIN user (select_related on the FK paths),
    #   3. one prefetch query for the tags M2M.
    with django_assert_num_queries(3):
        response = view(request)
        rows = response.data["results"]
    assert response.status_code == 200
    assert len(rows) == 3
    for row in rows:
        assert row["venue"]["name"] == "Arena"
        assert row["organizer"]["email"] == "organizer@example.com"
        assert {tag["name"] for tag in row["tags"]} == {"tag-0", "tag-1"}
