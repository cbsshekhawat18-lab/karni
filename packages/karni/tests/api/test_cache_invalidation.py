"""Response caching: every write path invalidates, once per call, through relations and expands."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache as default_cache
from django.db import connection, transaction
from django.test import Client
from django.test.utils import override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from karni.api import Access, BaseViewSet, HasRole, Public, caching
from karni.api.caching import dependencies, invalidate, invalidation_batch
from tests.testapp.models import Event, Tag, Venue

pytestmark = pytest.mark.django_db


class Events(BaseViewSet):
    model = Event
    access = Access(read=Public(), write=HasRole("staff"))
    auto_register = False


@pytest.fixture(autouse=True)
def _cache_on() -> Iterator[None]:
    default_cache.clear()
    with override_settings(KARNI_API_CACHE=True):
        yield
    default_cache.clear()


@pytest.fixture
def replaced(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Every call that replaces version tokens, with the keys it replaced."""
    calls: list[list[str]] = []
    original = caching._replace

    def spy(keys: Any) -> None:
        keys = list(keys)
        calls.append(keys)
        original(keys)

    monkeypatch.setattr(caching, "_replace", spy)
    return calls


@pytest.fixture
def events() -> list[Event]:
    venue = Venue.objects.create(name="Arena", city="Lyon")
    return [
        Event.objects.create(title=title, starts_at=timezone.now(), venue=venue)
        for title in ("One", "Two", "Three")
    ]


def _get(path: str = "/", action: str = "list", **kwargs: Any) -> Any:
    request = APIRequestFactory().get(path)
    return Events.as_view({"get": action})(request, **kwargs)


def _titles(path: str = "/") -> list[str]:
    return sorted(row["title"] for row in _get(path).data["results"])


def _detail(event: Event) -> Any:
    return _get(f"/events/{event.pk}/", "retrieve", pk=str(event.pk))


# through relations and ?expand=


def test_a_write_reaches_responses_through_an_expand_path(events: list[Event]) -> None:
    expanded = "/?expand=venue"
    assert _get(expanded).data["results"][0]["venue"]["name"] == "Arena"
    plain = _get()
    assert _get()["X-Cache"] == "HIT"
    Venue.objects.filter(pk=events[0].venue_id).update(name="Hall")
    response = _get(expanded)
    assert response["X-Cache"] == "MISS"
    assert {row["venue"]["name"] for row in response.data["results"]} == {"Hall"}
    assert plain.data == _get().data


def test_a_relation_the_serializer_renders_invalidates(events: list[Event]) -> None:
    tag = Tag.objects.create(name="jazz")
    events[0].tags.add(tag)
    _get()
    tag.delete()  # soft delete: the tag list of the event changes
    assert _get()["X-Cache"] == "MISS"


def test_the_dependency_graph_follows_every_allowed_expand_path() -> None:
    found = {model._meta.label for model in dependencies(Events)}
    assert {"testapp.Event", "testapp.Venue", "testapp.Tag"} <= found
    assert get_user_model()._meta.label in found  # ?expand=organizer is allowed


# Karni's querysets


def test_update_invalidates_lists_and_every_detail(
    events: list[Event], replaced: list[list[str]]
) -> None:
    _get()
    _detail(events[0])
    Event.objects.filter(title="One").update(title="Uno")
    assert len(replaced) == 1
    assert _titles() == ["Three", "Two", "Uno"]
    assert _detail(events[0]).data["title"] == "Uno"
    assert Event.objects.filter(title="nothing").update(title="x") == 0
    assert len(replaced) == 1  # no row changed: nothing to invalidate


def test_delete_soft_and_hard_invalidate(events: list[Event], replaced: list[list[str]]) -> None:
    _get()
    Event.objects.filter(title="One").delete()
    assert _titles() == ["Three", "Two"]
    Event.objects.filter(title="Two").hard_delete()
    assert _titles() == ["Three"]
    assert len(replaced) == 2


def test_bulk_create_and_bulk_update_invalidate_once(
    events: list[Event], replaced: list[list[str]]
) -> None:
    _get()
    made = Event.objects.bulk_create(
        [Event(title=f"New {n}", starts_at=timezone.now()) for n in range(3)]
    )
    assert len(_titles()) == 6 and len(replaced) == 1
    for row in events:
        row.title = row.title.upper()
    Event.objects.bulk_update(events, ["title"], batch_size=1)  # three UPDATEs, one invalidation
    assert len(replaced) == 2
    assert _titles()[3:] == ["ONE", "THREE", "TWO"] and len(made) == 3


def test_raw_sql_needs_invalidate_and_it_covers_details(events: list[Event]) -> None:
    _detail(events[0])
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {Event._meta.db_table} SET title = 'Raw'")
    assert _detail(events[0])["X-Cache"] == "HIT"  # Karni saw nothing
    invalidate(Event)
    fresh = _detail(events[0])
    assert fresh["X-Cache"] == "MISS" and fresh.data["title"] == "Raw"


def test_a_batch_invalidates_once_per_model(events: list[Event], replaced: list[list[str]]) -> None:
    with invalidation_batch():
        for row in events:
            row.title = f"{row.title}!"
            row.save()
        events[0].venue.save()
    assert len(replaced) == 1
    keys = replaced[0]
    assert "karni:api:m:testapp.event" in keys and "karni:api:a:testapp.event" in keys
    assert "karni:api:m:testapp.venue" in keys
    with invalidation_batch(discard=True):
        events[0].save()
    assert len(replaced) == 1


def test_a_write_in_a_transaction_invalidates_again_on_commit(
    events: list[Event],
    replaced: list[list[str]],
    django_capture_on_commit_callbacks: Any,
) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            events[0].save()
            assert len(replaced) == 1  # at once, for reads inside the transaction
    assert len(replaced) == 2  # and after the commit, for reads that raced it
    assert replaced[0] == replaced[1]


def test_nothing_is_written_while_caching_is_off(
    events: list[Event], replaced: list[list[str]]
) -> None:
    with override_settings(KARNI_API_CACHE=False):
        events[0].save()
        Event.objects.update(title="x")
        invalidate(Event)
    assert replaced == []


# the admin's bulk actions


def test_an_admin_bulk_action_invalidates_once(
    events: list[Event], replaced: list[list[str]]
) -> None:
    admin = get_user_model().objects.create_superuser(
        email="admin@example.com", password="pw-123456789"
    )
    client = Client()
    client.force_login(admin)
    _get()
    replaced.clear()
    response = client.post(
        "/admin/testapp/event/",
        {
            "action": "delete_selected",
            "_selected_action": [str(row.pk) for row in events[:2]],
            "post": "yes",
        },
    )
    assert response.status_code == 302
    assert Event.objects.count() == 1
    event_batches = [keys for keys in replaced if "karni:api:m:testapp.event" in keys]
    assert len(event_batches) == 1  # two soft deletes, one invalidation
    assert _titles() == ["Three"]
