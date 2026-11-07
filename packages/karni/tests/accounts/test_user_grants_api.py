"""Per-user grants over HTTP (experimental): the admin API, and ``Granted()`` in both auth modes.

The URLconf is built in this module while ``KARNI_USER_GRANTS`` is on: the
accounts routes (``permissions/grants/``) and a ``Granted()`` viewset over
``Event`` at ``api/granted-events/``. Clients sign in for real (a JWT access
token, or a session), so each request loads its own user and its own grants.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from types import ModuleType
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import include, path
from django.utils import timezone
from pytest_django import Settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from karni.accounts import grants
from karni.accounts.models import UserGrant
from karni.accounts.permissions import assign_role
from karni.accounts.roles import sync_roles
from karni.accounts.urls import build_urlpatterns
from karni.api import BaseViewSet, Granted
from karni.api.routers import KarniRouter
from karni.errorcodes import get as get_code
from tests.testapp.models import Event, Venue

pytestmark = pytest.mark.django_db

VIEW = "testapp.event:view"
APPROVE = "testapp.event:approve"
LIST = "/api/auth/permissions/grants/"
BULK = "/api/auth/permissions/grants/bulk/"
EVENTS = "/api/granted-events/"

ROLES = {
    "organizer": {"grants": {VIEW: "own", "testapp.event:add": "all"}},
    "support": {
        "grants": {
            VIEW: "all",
            "karni_accounts.usergrant:view": "all",
            "karni_accounts.usergrant:add": "all",
        }
    },
    "member": {"grants": {"karni_accounts.usergrant:view": "own"}},
    "ops": {"system": True, "grants": {"*": "all"}},
}


class GrantedEventViewSet(BaseViewSet):
    """Whatever the grants say for Event: roles and user grants."""

    model = Event
    access = Granted()
    auto_register = False


def _urlconf() -> ModuleType:
    router = KarniRouter()
    router.register("granted-events", GrantedEventViewSet, basename="granted-events")
    module = ModuleType("user_grants_urls")
    module.__dict__["urlpatterns"] = [
        path("api/auth/", include(build_urlpatterns())),
        path("api/", include(router.urls)),
    ]
    return module


@pytest.fixture(autouse=True)
def _world(settings: Settings) -> Iterator[None]:
    settings.KARNI_USER_GRANTS = True
    settings.KARNI_AUTH_MODE = "jwt"
    settings.ROOT_URLCONF = _urlconf()
    with override_settings(KARNI_ROLES=ROLES):
        sync_roles()
        yield


def _user(email: str, *roles: str, **flags: Any) -> Any:
    user = get_user_model().objects.create_user(email=email, password="s3cret-pass-123", **flags)
    for slug in roles:
        assign_role(user, slug)
    return user


def signed_in(user: Any) -> APIClient:
    """A client carrying the user's access token: every request loads the user anew."""
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def session_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_login(user)
    return client


@pytest.fixture
def place() -> tuple[Venue, Venue]:
    return Venue.objects.create(name="Arena", city="Pune"), Venue.objects.create(
        name="Hall", city="Jaipur"
    )


def _events(*titles_and_venues: tuple[str, Venue | None]) -> None:
    for title, venue in titles_and_venues:
        Event.objects.create(title=title, starts_at=timezone.now(), venue=venue)


def _titles(response: Any) -> set[str]:
    assert response.status_code == 200, response.content
    body = response.json()
    rows = body["results"] if isinstance(body, dict) else body
    return {row["title"] for row in rows}


def assert_refused(response: Any, code: str, status: int) -> dict[str, Any]:
    assert response.status_code == status, response.content
    body: dict[str, Any] = response.json()
    assert body["code"] == code and body["detail"].startswith(f"{code}: ")
    assert get_code(code) is not None
    return body


# the admin API


def test_add_list_change_and_revoke(place: tuple[Venue, Venue]) -> None:
    arena, hall = place
    ops = _user("ops@example.com", "ops")
    guest = _user("guest@example.com")
    client = signed_in(ops)
    later = (timezone.now() + timedelta(days=7)).isoformat()
    created = client.post(
        LIST,
        {
            "user": str(guest.pk),
            "permission": VIEW,
            "scope": "related:venue",
            "targets": [arena.pk],
            "expires_at": later,
            "reason": "pilot",
        },
        format="json",
    )
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["targets"] == [str(arena.pk)] and body["active"] is True
    assert body["granted_by"] == str(ops.pk) and body["reason"] == "pilot"
    grant_url = f"{LIST}{body['id']}/"

    listed = client.get(LIST, {"user": str(guest.pk)}).json()
    assert [row["id"] for row in listed["results"]] == [body["id"]]
    assert client.get(LIST, {"active": "false"}).json()["results"] == []
    assert client.get(grant_url).json()["permission"] == VIEW

    changed = client.patch(grant_url, {"targets": [arena.pk, hall.pk]}, format="json")
    assert changed.status_code == 200, changed.content
    assert changed.json()["targets"] == [str(arena.pk), str(hall.pk)]
    expired = client.patch(grant_url, {"expires_at": timezone.now().isoformat()}, format="json")
    assert expired.json()["active"] is False
    assert len(client.get(LIST, {"active": "false"}).json()["results"]) == 1

    assert client.delete(grant_url).status_code == 204
    assert client.get(grant_url).status_code == 404
    assert not UserGrant.objects.exists()


def test_bulk_grants_one_pattern_to_many_users() -> None:
    ops = _user("ops@example.com", "ops")
    people = [_user(f"p{n}@example.com") for n in range(3)]
    response = signed_in(ops).post(
        BULK,
        {"users": [str(p.pk) for p in people], "permission": "testapp.event:*", "scope": "all"},
        format="json",
    )
    assert response.status_code == 201, response.content
    assert {row["user"] for row in response.json()} == {str(p.pk) for p in people}
    assert UserGrant.objects.filter(granted_by=ops).count() == 3
    for person in people:
        assert signed_in(person).get(EVENTS).status_code == 200


def test_a_bulk_grant_with_a_bad_user_or_pattern_writes_nothing() -> None:
    ops = _user("ops@example.com", "ops")
    guest = _user("guest@example.com")
    client = signed_in(ops)
    unknown = client.post(
        BULK, {"users": [str(guest.pk), "999999"], "permission": VIEW}, format="json"
    )
    assert unknown.status_code == 400 and "users" in unknown.json()
    bad = client.post(
        BULK, {"users": [str(guest.pk)], "permission": "testapp.nope:*"}, format="json"
    )
    assert assert_refused(bad, "E360", 400)["field"] == "permission"
    assert client.post(BULK, {"users": [], "permission": VIEW}, format="json").status_code == 400
    assert not UserGrant.objects.exists()


@pytest.mark.parametrize(
    ("body", "code", "field"),
    [
        ({"permission": "testapp.event:aprove"}, "E360", "permission"),
        ({"permission": VIEW, "scope": "related:city"}, "E361", "scope"),
        ({"permission": VIEW, "scope": "all", "targets": ["1"]}, "E362", "targets"),
    ],
)
def test_a_bad_grant_is_a_coded_400(body: dict[str, Any], code: str, field: str) -> None:
    ops = _user("ops@example.com", "ops")
    guest = _user("guest@example.com")
    response = signed_in(ops).post(LIST, {"user": str(guest.pk), **body}, format="json")
    assert assert_refused(response, code, 400)["field"] == field


def test_the_operator_grants_only_what_they_hold() -> None:
    support = _user("support@example.com", "support")
    guest = _user("guest@example.com")
    client = signed_in(support)
    refused = client.post(
        LIST, {"user": str(guest.pk), "permission": APPROVE, "scope": "all"}, format="json"
    )
    body = assert_refused(refused, "E363", 403)
    assert body["reasons"] == ["you do not hold testapp.event:approve, so you cannot grant it."]
    allowed = client.post(LIST, {"user": str(guest.pk), "permission": VIEW}, format="json")
    assert allowed.status_code == 201
    grant_url = f"{LIST}{allowed.json()['id']}/"
    # support may add and view, not change or delete
    assert client.patch(grant_url, {"reason": "x"}, format="json").status_code == 403
    assert client.delete(grant_url).status_code == 403


def test_the_gate_and_the_rows_follow_the_usergrant_grants() -> None:
    ops = _user("ops@example.com", "ops")
    member = _user("member@example.com", "member")
    other = _user("other@example.com")
    mine = grants.grant(ops, member, VIEW, "all")
    grants.grant(ops, other, VIEW, "all")
    client = signed_in(member)
    assert [row["id"] for row in client.get(LIST).json()["results"]] == [str(mine.pk)]
    theirs = UserGrant.objects.get(user=other)
    assert client.get(f"{LIST}{theirs.pk}/").status_code == 404
    assert client.post(LIST, {"user": str(member.pk), "permission": VIEW}).status_code == 403
    assert APIClient().get(LIST).status_code in (401, 403)
    organizer = _user("o@example.com", "organizer")
    assert signed_in(organizer).get(LIST).status_code == 403


def test_a_urlconf_built_while_on_answers_e364_once_off(settings: Settings) -> None:
    ops = _user("ops@example.com", "ops")
    settings.KARNI_USER_GRANTS = False
    client = signed_in(ops)
    assert_refused(client.get(LIST), "E364", 404)
    assert_refused(client.post(BULK, {"users": [], "permission": VIEW}, format="json"), "E364", 404)


def test_the_routes_exist_only_while_on(settings: Settings) -> None:
    from karni.testing.schema import generate_schema

    paths = set(generate_schema()["paths"])
    assert {LIST, BULK} <= paths and any(p.startswith(LIST + "{") for p in paths), paths
    settings.KARNI_USER_GRANTS = False
    settings.ROOT_URLCONF = _urlconf()
    assert not {LIST, BULK} & set(generate_schema()["paths"])


# Granted() reads the union, in both auth modes


@pytest.mark.parametrize("mode", ["jwt", "session"])
def test_granted_reads_roles_and_user_grants(
    mode: str, settings: Settings, place: tuple[Venue, Venue]
) -> None:
    arena, hall = place
    settings.KARNI_AUTH_MODE = mode
    alice = _user("alice@example.com", "organizer")
    Event.objects.create(title="Mine", starts_at=timezone.now(), organizer=alice, venue=hall)
    _events(("At arena", arena), ("At hall", hall))
    client = signed_in(alice) if mode == "jwt" else session_client(alice)
    assert _titles(client.get(EVENTS)) == {"Mine"}
    grants.grant(None, alice, VIEW, "related:venue", targets=[arena.pk])
    assert _titles(client.get(EVENTS)) == {"Mine", "At arena"}
    at_hall = Event.objects.get(title="At hall")
    assert client.get(f"{EVENTS}{at_hall.pk}/").status_code == 404
    settings.KARNI_USER_GRANTS = False
    assert _titles(client.get(EVENTS)) == {"Mine"}


def test_a_request_pays_one_query_for_user_grants_however_many_rows(
    settings: Settings, place: tuple[Venue, Venue]
) -> None:
    arena, hall = place
    alice = _user("alice@example.com", "organizer")
    Event.objects.create(title="Mine", starts_at=timezone.now(), organizer=alice)
    for venue in place:
        grants.grant(None, alice, VIEW, "related:venue", targets=[venue.pk])
    client = signed_in(alice)

    def count(path: str) -> int:
        with CaptureQueriesContext(connection) as queries:
            assert client.get(path).status_code == 200
        return len(queries)

    _events(("One", arena))
    few = count(EVENTS)
    _events(*((f"Event {n}", hall) for n in range(30)))
    many = count(EVENTS)
    assert few == many
    settings.KARNI_USER_GRANTS = False
    assert count(EVENTS) == many - 1
