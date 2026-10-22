"""karni.testing.hidden: assert_row_hidden and its admin twin, passing and failing on purpose."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.test import override_settings
from django.utils import timezone

from karni.accounts.roles import sync_roles
from karni.testing import (
    APITestCase,
    assert_admin_row_hidden,
    assert_row_hidden,
    client_as,
    user_with_roles,
)
from karni.testing.hidden import ADMIN_ROW_CHECKS, ROW_CHECKS, HiddenRowProbe
from tests.testapp.models import Event, Tag
from tests.testing import hidden_urls
from tests.testing.hidden_urls import HiddenEventViewSet, World, make_world

pytestmark = pytest.mark.django_db

ROUTES = override_settings(
    ROOT_URLCONF="tests.testing.hidden_urls",
    KARNI_API_ROUTER="tests.testing.hidden_urls.get_router",
    KARNI_ROLES=hidden_urls.ROLES,
)
LEAKY_ROUTES = override_settings(
    ROOT_URLCONF="tests.testing.hidden_leaky_urls",
    KARNI_API_ROUTER="tests.testing.hidden_leaky_urls.get_router",
)


@pytest.fixture(autouse=True)
def _routes() -> Iterator[None]:
    with ROUTES:
        sync_roles()
        yield


@pytest.fixture
def world() -> World:
    return make_world()


def _staff(user: Any) -> Any:
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    user.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label="testapp",
            codename__in=["view_event", "change_event", "delete_event"],
        )
    )
    return user


def _leaks(*expected: str, **call: Any) -> str:
    with pytest.raises(AssertionError) as caught:
        assert_row_hidden(**call)
    message = str(caught.value)
    assert "E606" in message, message
    for fragment in expected:
        assert fragment in message, message
    return message


# the one-liner passes where Karni scopes rows


def test_a_row_outside_an_own_grant_is_hidden_on_every_surface(world: World) -> None:
    me = client_as(user=world.alice)
    report = assert_row_hidden(me, "/api/events/", world.theirs, visible=world.mine)
    assert report.passed == list(ROW_CHECKS) and not report.failures
    # Bob's event is reached from venues (?expand=events) and exported nowhere else.
    assert not any(note.startswith("expand:") for note in report.notes), report.notes


def test_a_row_outside_a_where_is_hidden_and_never_inlined(world: World) -> None:
    me = client_as(user=world.alice)
    report = assert_row_hidden(me, "/api/venues/", world.rome, visible=world.berlin)
    assert report.passed == list(ROW_CHECKS)


def test_the_history_action_is_probed_for_audited_resources(world: World) -> None:
    report = assert_row_hidden(world.alice, "/api/prices/", world.pound, visible=world.euro)
    assert "actions" in report.passed
    assert not any(note.startswith("actions:") for note in report.notes)


def test_the_resource_can_be_named_like_assert_crud_names_it(world: World) -> None:
    me = client_as(user=world.alice)
    for resource in (HiddenEventViewSet, Event, "testapp.Event"):
        report = assert_row_hidden(me, resource, world.theirs, visible=world.mine, checks=["list"])
        assert report.passed == ["list"]


def test_each_check_runs_on_its_own_and_unknown_names_are_refused(world: World) -> None:
    me = client_as(user=world.alice)
    for name in ROW_CHECKS:
        report = assert_row_hidden(me, "/api/events/", world.theirs, checks=[name])
        assert report.passed == [name]
    skipped = assert_row_hidden(me, "/api/events/", world.theirs, skip=["export", "expand"])
    assert skipped.passed == [n for n in ROW_CHECKS if n not in {"export", "expand"}]
    with pytest.raises(AssertionError, match="E603") as caught:
        assert_row_hidden(me, "/api/events/", world.theirs, checks=["exports"])
    assert "the checks are: detail, actions, list" in str(caught.value)


def test_a_search_term_only_the_hidden_row_matches_must_find_nothing(world: World) -> None:
    me = client_as(user=world.alice)
    assert_row_hidden(me, "/api/events/", world.theirs, checks=["search"], search="zeppelin")
    with pytest.raises(AssertionError, match="search= names a term only the hidden row"):
        assert_row_hidden(me, "/api/events/", world.theirs, checks=["search"], search="keynote")


class HiddenRowMethodTests(APITestCase):
    def test_assert_row_hidden_as_a_method(self) -> None:
        sync_roles()  # the module's routes and roles are on (autouse fixture)
        world = make_world()
        client = self.client_as(user=world.alice)
        report = self.assert_row_hidden(client, "/api/events/", world.theirs, checks=["list"])
        assert report.passed == ["list"]
        admin_report = self.assert_admin_row_hidden(
            _staff(world.alice), world.theirs, checks=["changelist"]
        )
        assert admin_report.passed == ["changelist"]


# nothing to prove: the run says so (E616) instead of passing


def test_a_client_that_cannot_list_proves_no_row_scope(world: World) -> None:
    me = client_as(user=world.alice)  # no tagger role: every tag is out of reach
    with pytest.raises(AssertionError) as caught:
        assert_row_hidden(me, "/api/tags/", world.tag, checks=["list"])
    message = str(caught.value)
    assert "E616" in message and "the client cannot list the resource" in message


def test_a_client_that_sees_no_row_at_all_proves_nothing(world: World) -> None:
    newcomer = client_as(user=user_with_roles("organizer"))  # no event of their own
    with pytest.raises(AssertionError, match="positive control") as caught:
        assert_row_hidden(newcomer, "/api/events/", world.theirs, checks=["list"])
    assert "E616" in str(caught.value)
    with pytest.raises(AssertionError, match="does not list the visible row"):
        assert_row_hidden(newcomer, "/api/events/", world.theirs, visible=world.mine)


def test_a_url_that_is_not_a_list_route_is_refused(world: World) -> None:
    me = client_as(user=world.alice)
    with pytest.raises(AssertionError, match="not a viewset's list route"):
        assert_row_hidden(me, f"/api/events/{world.mine.pk}/", world.theirs)
    with pytest.raises(AssertionError, match="resolves to no view"):
        assert_row_hidden(me, "/nowhere/", world.theirs)


# every leak is caught and named


def test_a_viewset_that_bypasses_its_read_scope(world: World) -> None:
    with LEAKY_ROUTES:
        url = "/api/leaky-events/"
        message = _leaks(
            f"detail: GET {url}{world.theirs.pk}/ answered 200, expected 404",
            f"list: GET {url} returns the hidden row",
            "narrow the viewset's access.read",
            client=client_as(user=world.alice),
            resource=url,
            row=world.theirs,
            visible=world.mine,
        )
        assert f"filters: GET {url}?organizer={world.bob.pk}" in message
        assert f"search: GET {url}?search=zeppelin returns the hidden row" in message
        assert f"export: GET {url}export/?format=xlsx writes the hidden row" in message


def test_a_403_that_confirms_the_row_exists(world: World) -> None:
    with LEAKY_ROUTES:
        url = f"/api/forbidding-events/{world.theirs.pk}/"
        _leaks(
            f"detail: GET {url} answered 403 for the hidden row but 404 for a row that does "
            "not exist (a 403 confirms the row exists)",
            f"detail: DELETE {url} answered 403",
            "never raise PermissionDenied for a row the client cannot see",
            client=client_as(user=world.alice),
            resource="/api/forbidding-events/",
            row=world.theirs,
            visible=world.mine,
            checks=["detail", "actions"],
        )


def test_a_serializer_that_inlines_a_hidden_related_row(world: World) -> None:
    """Reads go through the optimiser's scoped lookups; a write's response did not."""
    with LEAKY_ROUTES:
        message = _leaks(
            f"expand: PATCH /api/inlining-events/{world.mine.pk}/?expand=venue answers with "
            f"the hidden Venue {world.rome.pk} embedded",
            "karni.api.related.readable_related",
            client=client_as(user=world.alice),
            resource="/api/venues/",
            row=world.rome,
            visible=world.berlin,
            checks=["expand"],
        )
        assert f"GET /api/inlining-events/{world.mine.pk}/?expand=venue" not in message


def test_an_order_that_repeats_rows(world: World) -> None:
    world.mine.tags.add(Tag.objects.create(name="two"))
    Event.objects.create(title="Second", starts_at=timezone.now(), organizer=world.alice)
    with LEAKY_ROUTES:
        message = _leaks(
            "Leave to-many relations out of ordering_fields",
            client=client_as(user=world.alice),
            resource="/api/tag-ordered-events/",
            row=world.theirs,
            visible=world.mine,
            checks=["ordering"],
        )
    # Either direction proves it: the database decides which one repeats a row
    # first (PostgreSQL sorts NULLs last ascending, SQLite first).
    repeated = r"ordering: GET /api/tag-ordered-events/\?ordering=-?tags repeats row"
    assert re.search(repeated, message), message


def test_a_count_that_includes_hidden_rows(world: World) -> None:
    with LEAKY_ROUTES:
        _leaks(
            "list: GET /api/overcounting-events/: count is 2 but the pages hold 1 row(s)",
            client=client_as(user=world.alice),
            resource="/api/overcounting-events/",
            row=world.theirs,
            visible=world.mine,
            checks=["list"],
        )


def test_an_export_of_rows_outside_the_scope(world: World) -> None:
    with LEAKY_ROUTES:
        message = _leaks(
            "export: GET /api/export-leak-events/export/?format=csv writes the hidden row",
            "writes 2 row(s) but the list holds 1",
            client=client_as(user=world.alice),
            resource="/api/export-leak-events/",
            row=world.theirs,
            visible=world.mine,
            checks=["export"],
        )
        assert "format=xlsx" in message


def test_a_subclass_replaces_one_check(world: World) -> None:
    class Lenient(HiddenRowProbe):
        def check_export(self) -> None:
            self.note("export", "exports are audited elsewhere")

    with LEAKY_ROUTES:
        report = assert_row_hidden(
            client_as(user=world.alice),
            "/api/export-leak-events/",
            world.theirs,
            visible=world.mine,
            checks=["export"],
            probe=Lenient,
        )
    assert report.notes == ["export: exports are audited elsewhere"]


# the admin


def test_the_admin_treats_the_hidden_row_as_missing(world: World) -> None:
    report = assert_admin_row_hidden(_staff(world.alice), world.theirs, visible=world.mine)
    assert report.passed == list(ADMIN_ROW_CHECKS) and not report.failures


def test_an_exempt_admin_lists_the_hidden_row(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    registered = type(admin.site._registry[Event])
    monkeypatch.setattr(registered, "scope_exempt", True)
    monkeypatch.setattr(registered, "scope_exempt_reason", "support sees every event")
    with pytest.raises(AssertionError) as caught:
        assert_admin_row_hidden(_staff(world.alice), world.theirs, visible=world.mine)
    message = str(caught.value)
    assert "E606" in message
    assert "changelist: GET /admin/testapp/event/ lists the hidden row" in message
    assert "views: GET /admin/testapp/event/" in message and "answered 200" in message


def test_an_admin_that_denies_instead_of_not_finding(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    registered = type(admin.site._registry[Event])

    def unscoped(self: Any, request: Any, object_id: str, from_field: Any = None) -> Any:
        return Event._base_manager.filter(pk=object_id).first()

    monkeypatch.setattr(registered, "get_object", unscoped)
    with pytest.raises(AssertionError) as caught:
        assert_admin_row_hidden(_staff(world.alice), world.theirs, checks=["views", "writes"])
    message = str(caught.value)
    url = f"/admin/testapp/event/{world.theirs.pk}/change/"
    assert f"views: GET {url} answered 403 (no redirect) for the hidden row but 302" in message
    assert "(a 403 confirms the row exists)" in message
    assert "Django's admin answers a row it cannot find with a redirect" in message


def test_an_admin_user_who_cannot_open_the_changelist_proves_nothing(world: World) -> None:
    with pytest.raises(AssertionError) as caught:
        assert_admin_row_hidden(world.alice, world.theirs)  # not staff
    message = str(caught.value)
    assert "E616" in message and "the user cannot open it" in message
