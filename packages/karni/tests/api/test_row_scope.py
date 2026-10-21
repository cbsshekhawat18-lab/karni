"""Row scope, not role: a user who may list a resource never learns about a row outside their scope.

The denial probes elsewhere mostly exercise a *role* refusal (no grant at
all, a 403 for every row alike). Here Alice may list every resource, and
each row hidden from her is outside her *row* scope: Bob's event (an
``own`` grant), a venue outside Berlin (``Where``), a tag (a role she does
not hold), a price not in EUR (``Where``, audited so ``/history/`` is
routed). Every surface must treat that row exactly like one that does not
exist. ``tests/testing/test_hidden.py`` drives the same surfaces through the
one-line helper.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import Client, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from karni.accounts.roles import sync_roles
from karni.testing import client_as, user_with_roles
from karni.transfer.formats import read_table
from tests.testapp.models import Event, Tag, Venue
from tests.testing import hidden_urls
from tests.testing.hidden_urls import HiddenEventViewSet, World, make_world

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _routes() -> Iterator[None]:
    with override_settings(
        ROOT_URLCONF="tests.testing.hidden_urls",
        KARNI_API_ROUTER="tests.testing.hidden_urls.get_router",
        KARNI_ROLES=hidden_urls.ROLES,
    ):
        sync_roles()
        yield


@pytest.fixture
def world() -> World:
    return make_world()


def _body(response: Any) -> bytes:
    if getattr(response, "streaming", False):
        return b"".join(response.streaming_content)
    content: bytes = response.content
    return content


def _rows(response: Any) -> list[dict[str, Any]]:
    assert response.status_code == 200, response.content
    data = response.json()
    return list(data["results"]) if isinstance(data, dict) else list(data)


def _ids(response: Any) -> list[str]:
    return [str(row["id"]) for row in _rows(response)]


# 1. detail by id, the write verbs, Karni's detail actions


def test_every_verb_on_a_hidden_row_answers_like_a_missing_row(world: World) -> None:
    me = client_as(user=world.alice)
    hidden, missing = world.theirs.pk, uuid.uuid4()
    before = Event.objects.filter(pk=hidden).values().first()
    for method in ("get", "patch", "put", "delete"):
        call = getattr(me, method)
        answered = call(f"/api/events/{hidden}/", {}, format="json")
        absent = call(f"/api/events/{missing}/", {}, format="json")
        assert answered.status_code == absent.status_code == 404, method
        assert answered.json() == absent.json(), method  # the same error: no oracle
    assert Event.objects.filter(pk=hidden).values().first() == before


def test_the_history_action_hides_the_row_too(world: World) -> None:
    me = client_as(user=world.alice)
    hidden = me.get(f"/api/prices/{world.pound.pk}/history/")
    absent = me.get(f"/api/prices/{uuid.uuid4()}/history/")
    assert hidden.status_code == absent.status_code == 404
    assert hidden.json() == absent.json()
    assert me.get(f"/api/prices/{world.euro.pk}/history/").status_code == 200


# 2. ?expand= (and to-many key lists) never inline a related row the user cannot see


def test_a_write_response_inlines_no_hidden_related_row(world: World) -> None:
    """Regression: create/update rendered the saved row's relations unscoped."""
    me = client_as(user=world.alice)
    url = f"/api/events/{world.mine.pk}/"
    patched = me.patch(f"{url}?expand=venue,tags", {}, format="json")
    assert patched.status_code == 200, patched.content
    assert patched.json()["venue"] is None  # Rome is not Alice's to read
    assert patched.json()["tags"] == []  # nor is the tag
    assert me.patch(url, {}, format="json").json()["tags"] == []  # the key list too
    put = me.put(
        f"{url}?expand=venue",
        {"title": "Alice keynote", "starts_at": "2030-01-01T10:00:00Z"},
        format="json",
    )
    assert put.status_code == 200 and put.json()["venue"] is None
    # The other direction: Bob's event reached from a venue Alice may read and write.
    reverse = me.patch(f"/api/venues/{world.berlin.pk}/?expand=events", {}, format="json")
    assert reverse.status_code == 200 and reverse.json()["events"] == []


def test_reads_inline_no_hidden_related_row(world: World) -> None:
    me = client_as(user=world.alice)
    listed = _rows(me.get("/api/events/", {"expand": "venue,tags"}))
    assert [(row["venue"], row["tags"]) for row in listed] == [(None, [])]
    detail = me.get(f"/api/events/{world.mine.pk}/", {"expand": "venue,tags"}).json()
    assert detail["venue"] is None and detail["tags"] == []
    venue = me.get(f"/api/venues/{world.berlin.pk}/", {"expand": "events"}).json()
    assert venue["events"] == []


@pytest.mark.parametrize(
    "declared",
    [
        {"optimize": False},
        {"select_related": ["venue"]},
        {"prefetch_related": ["tags"]},
    ],
    ids=["optimize-off", "select-hint", "prefetch-hint"],
)
def test_performance_declarations_never_widen_what_is_inlined(
    world: World, monkeypatch: pytest.MonkeyPatch, declared: dict[str, Any]
) -> None:
    """Regression: a hint (or optimize = False) replaced the scoped lookup and inlined anyway."""
    for name, value in declared.items():
        monkeypatch.setattr(HiddenEventViewSet, name, value)
    me = client_as(user=world.alice)
    for response in (
        me.get("/api/events/", {"expand": "venue,tags"}),
        me.get(f"/api/events/{world.mine.pk}/", {"expand": "venue,tags"}),
    ):
        data = response.json()
        row = data["results"][0] if "results" in data else data
        assert row["venue"] is None and row["tags"] == [], row
    assert _rows(me.get("/api/events/"))[0]["tags"] == []


def test_a_hint_costs_no_extra_query_per_row(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """The render-time check batches: one query per related model, not per row."""
    monkeypatch.setattr(HiddenEventViewSet, "select_related", ["venue"])
    monkeypatch.setattr(HiddenEventViewSet, "prefetch_related", ["tags"])
    me = client_as(user=world.alice)

    def queries() -> int:
        with CaptureQueriesContext(connection) as captured:
            assert me.get("/api/events/", {"expand": "venue,tags"}).status_code == 200
        return len(captured)

    queries()  # warm: the user's grants are cached on the user after the first request
    small = queries()
    for index in range(4):
        event = Event.objects.create(
            title=f"More {index}",
            starts_at=timezone.now(),
            organizer=world.alice,
            venue=Venue.objects.create(name=f"Hall {index}", city="Rome"),
        )
        event.tags.add(Tag.objects.create(name=f"t{index}"))
    assert queries() == small


# 3. filters


def test_filters_never_return_or_count_the_hidden_row(world: World) -> None:
    me = client_as(user=world.alice)
    theirs = world.theirs
    for params in (
        {"organizer": str(world.bob.pk)},
        {"venue": str(world.berlin.pk)},
        {"title": theirs.title},
        {"title__icontains": "zeppelin"},
    ):
        response = me.get("/api/events/", params)
        assert response.json()["count"] == 0 and _ids(response) == [], params
    unknown = me.get("/api/events/", {"id": str(theirs.pk)})  # not a filter: ignored
    assert _ids(unknown) == [str(world.mine.pk)] and unknown.json()["count"] == 1


def test_a_relation_filter_does_not_confirm_a_hidden_row_exists(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: filterset_fields' choice filters accepted any row's key (200 vs 400)."""
    monkeypatch.setattr(HiddenEventViewSet, "filterset_fields", ["venue"], raising=False)
    naples = Venue.objects.create(name="San Carlo", city="Naples")  # hidden, unreferenced
    me = client_as(user=world.alice)
    hidden = me.get("/api/events/", {"venue": str(naples.pk)})
    absent = me.get("/api/events/", {"venue": str(uuid.uuid4())})
    assert hidden.status_code == absent.status_code == 400
    assert hidden.json() == absent.json()
    readable = me.get("/api/events/", {"venue": str(world.berlin.pk)})
    assert readable.status_code == 200 and readable.json()["count"] == 0


# 4. search


def test_a_search_matching_only_the_hidden_row_finds_nothing(world: World) -> None:
    me = client_as(user=world.alice)
    response = me.get("/api/events/", {"search": "zeppelin"})
    assert response.json()["count"] == 0 and _ids(response) == []
    prices = me.get("/api/prices/", {"search": "sterling"})
    assert prices.json()["count"] == 0


# 5. ordering


def test_ordering_by_a_to_many_relation_neither_repeats_nor_drops_rows(world: World) -> None:
    """Regression: ?ordering=-tags returned one row per tag (hidden ones included)."""
    second = Event.objects.create(title="Second", starts_at=timezone.now(), organizer=world.alice)
    world.mine.tags.add(Tag.objects.create(name="two"), Tag.objects.create(name="three"))
    me = client_as(user=world.alice)
    expected = {str(world.mine.pk), str(second.pk)}
    for term in ("tags", "-tags", "title", "-venue", "organizer"):
        response = me.get("/api/events/", {"ordering": term})
        ids = _ids(response)
        assert sorted(ids) == sorted(expected) and response.json()["count"] == 2, term


def test_ordering_by_a_relation_orders_by_its_key_not_the_related_row(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: ?ordering=venue sorted by the venue's own Meta.ordering (a hidden name)."""
    low, high = sorted(
        (Venue.objects.create(name="?", city="Rome") for _ in range(2)), key=lambda v: str(v.pk)
    )
    Venue.objects.filter(pk=low.pk).update(name="Zeta")  # names sort the other way round
    Venue.objects.filter(pk=high.pk).update(name="Alpha")
    first = Event.objects.create(
        title="At low", starts_at=timezone.now(), organizer=world.alice, venue=low
    )
    second = Event.objects.create(
        title="At high", starts_at=timezone.now(), organizer=world.alice, venue=high
    )
    world.mine.delete()
    monkeypatch.setattr(Venue._meta, "ordering", ["name"])
    me = client_as(user=world.alice)
    assert _ids(me.get("/api/events/", {"ordering": "venue"})) == [str(first.pk), str(second.pk)]
    assert _ids(me.get("/api/events/", {"ordering": "-venue"})) == [str(second.pk), str(first.pk)]


def test_ordering_by_a_field_the_user_cannot_read_is_ignored(world: World) -> None:
    other = Event.objects.create(
        title="Other", starts_at=timezone.now(), organizer=world.alice, internal_note="zzz"
    )
    Event.objects.filter(pk=world.mine.pk).update(internal_note="aaa")
    me = client_as(user=world.alice)
    default = _ids(me.get("/api/events/"))
    assert _ids(me.get("/api/events/", {"ordering": "internal_note"})) == default
    assert _ids(me.get("/api/events/", {"ordering": "-internal_note"})) == default
    assert str(other.pk) in default


# 6. the admin


def _staff(user: Any) -> Client:
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    user.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label="testapp",
            codename__in=["view_event", "change_event", "delete_event"],
        )
    )
    client = Client()
    client.force_login(user)
    return client


def test_the_admin_treats_a_row_outside_the_scope_as_missing(world: World) -> None:
    client = _staff(world.alice)
    changelist = client.get("/admin/testapp/event/")
    shown = {str(pk) for pk in changelist.context_data["cl"].queryset.values_list("pk", flat=True)}
    assert shown == {str(world.mine.pk)}
    searched = client.get("/admin/testapp/event/", {"q": "zeppelin"})
    assert not searched.context_data["cl"].queryset.exists()
    before = Event.objects.filter(pk=world.theirs.pk).values().first()
    for view, data in (("change", {"_save": "1"}), ("history", None), ("delete", {"post": "yes"})):
        for method in ("get", "post") if data else ("get",):
            send = getattr(client, method)
            args = (data,) if method == "post" else ()
            hidden = send(f"/admin/testapp/event/{world.theirs.pk}/{view}/", *args)
            absent = send(f"/admin/testapp/event/{uuid.uuid4()}/{view}/", *args)
            assert hidden.status_code == absent.status_code == 302, (view, method)
            assert hidden["Location"] == absent["Location"] == "/admin/", (view, method)
    assert Event.objects.filter(pk=world.theirs.pk).values().first() == before


# 7. export


def _export(client: Any, url: str, fmt: str, **params: str) -> tuple[list[str], list[list[Any]]]:
    response = client.get(url, {"format": fmt, **params})
    assert response.status_code == 200, response.content
    return read_table(io.BytesIO(_body(response)), fmt)


@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_an_export_never_writes_the_hidden_row(world: World, fmt: str) -> None:
    me = client_as(user=world.alice)
    for params in ({}, {"search": "zeppelin"}, {"organizer": str(world.bob.pk)}):
        headers, rows = _export(me, "/api/events/export/", fmt, **params)
        ids = [str(row[headers.index("id")]) for row in rows]
        assert str(world.theirs.pk) not in ids, params
        assert ids == ([str(world.mine.pk)] if not params else []), params


@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_an_export_names_only_the_related_rows_the_user_may_read(world: World, fmt: str) -> None:
    """Regression: the natural key of a hidden related row (the venue's name) was exported."""
    readable = Event.objects.create(
        title="In Berlin", starts_at=timezone.now(), organizer=world.alice, venue=world.berlin
    )
    me = client_as(user=world.alice)
    headers, rows = _export(me, "/api/events/export/", fmt)
    venues = {str(row[headers.index("id")]): str(row[headers.index("venue")]) for row in rows}
    assert venues[str(readable.pk)] == "Arena"  # readable: named
    assert venues[str(world.mine.pk)] == str(world.rome.pk)  # hidden: its key, as the API shows
    assert "Colosseo" not in str(rows) and "secret" not in str(rows)


def test_the_admin_export_names_related_rows_by_the_admin_scope(world: World) -> None:
    """In the admin, related rows follow the admin's grants, not the API's read scope."""
    planner = user_with_roles("planner")  # own events, no venue grant in the admin
    planned = Event.objects.create(
        title="Planned", starts_at=timezone.now(), organizer=planner, venue=world.rome
    )
    for user, event, shown in ((world.alice, world.mine, "Colosseo"), (planner, planned, None)):
        client = _staff(user)
        response = client.post(
            "/admin/testapp/event/",
            {"action": "export_csv", "_selected_action": [str(event.pk), str(world.theirs.pk)]},
        )
        assert response.status_code == 200
        headers, rows = read_table(io.BytesIO(_body(response)), "csv")
        assert [str(row[headers.index("id")]) for row in rows] == [str(event.pk)]
        venue = str(rows[0][headers.index("venue")])
        assert venue == (shown or str(world.rome.pk)), user
