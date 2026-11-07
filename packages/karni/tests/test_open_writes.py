"""karni.W102: a routed viewset any self-registered user may change and delete, row by row.

The 0.4.0 ``--access public-read`` preset generated ``write=Authenticated()``.
With open registration that hands every row to anyone who signs up. The
check reports it at boot, and stays silent for the declarations that narrow
writes (Owned, HasRole, Granted, Can) and when registration is closed.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.test import override_settings

from karni.api.access import (
    Access,
    Authenticated,
    Can,
    Granted,
    HasRole,
    Owned,
    Predicate,
    Public,
    Where,
    admits_every_user,
)
from karni.api.routers import KarniRouter
from karni.api.viewsets import BaseViewSet
from karni.checks import check_open_writes
from karni.errorcodes import docs_url
from tests.testapp.models import Event, Venue

pytestmark = pytest.mark.django_db


class OpenVenueViewSet(BaseViewSet):
    model = Venue
    access = Access(read=Public(), write=Authenticated())


class PublicWriteVenueViewSet(BaseViewSet):
    model = Venue
    access = Access(read=Public(), write=Public())


class StaffVenueViewSet(BaseViewSet):
    model = Venue
    access = Access(read=Public(), write=HasRole("staff"))


class GrantedVenueViewSet(BaseViewSet):
    model = Venue
    access = Granted()


class GrantedWriteVenueViewSet(BaseViewSet):
    model = Venue
    access = Access(read=Public(), write=Granted())


class OwnedEventViewSet(BaseViewSet):
    model = Event
    access = Access(read=Public(), write=Owned("organizer"))


class UserContentEventViewSet(BaseViewSet):
    """The user-generated-content pattern: anyone signed in adds, owners change their own."""

    model = Event
    access = Access(read=Public(), write=Owned("organizer"), create=Authenticated())


class NarrowedEventViewSet(BaseViewSet):
    model = Event
    access = Access(read=Public(), write=Authenticated() & HasRole("editor"))


def open_router() -> Any:
    router = KarniRouter()
    router.register("open-venues", OpenVenueViewSet, basename="open-venues")
    router.register("public-write-venues", PublicWriteVenueViewSet, basename="pw-venues")
    return router


def narrowed_router() -> Any:
    router = KarniRouter()
    for prefix, viewset in (
        ("staff-venues", StaffVenueViewSet),
        ("granted-venues", GrantedVenueViewSet),
        ("granted-write-venues", GrantedWriteVenueViewSet),
        ("owned-events", OwnedEventViewSet),
        ("ugc-events", UserContentEventViewSet),
        ("narrowed-events", NarrowedEventViewSet),
    ):
        router.register(prefix, viewset, basename=prefix)
    return router


@override_settings(
    KARNI_API_ROUTER="tests.test_open_writes.open_router", KARNI_ACCOUNTS_REGISTRATION=True
)
def test_an_open_write_warns_while_registration_is_open() -> None:
    messages = check_open_writes()
    assert [(m.id, m.obj) for m in messages] == [
        ("karni.W102", OpenVenueViewSet),
        ("karni.W102", PublicWriteVenueViewSet),
    ]
    first = messages[0]
    assert first.msg.startswith(
        "OpenVenueViewSet lets any self-registered user change and delete every Venue"
    )
    assert "write=Authenticated()" in first.msg
    assert 'HasRole("staff")' in first.hint
    assert "KARNI_ACCOUNTS_REGISTRATION = False" in first.hint
    assert first.hint.endswith(f"See {docs_url('W102')}")


@override_settings(
    KARNI_API_ROUTER="tests.test_open_writes.open_router", KARNI_ACCOUNTS_REGISTRATION=False
)
def test_closed_registration_silences_it() -> None:
    assert check_open_writes() == []


@override_settings(
    KARNI_API_ROUTER="tests.test_open_writes.narrowed_router", KARNI_ACCOUNTS_REGISTRATION=True
)
def test_owned_role_and_granted_writes_are_not_reported() -> None:
    assert check_open_writes() == []


@override_settings(
    KARNI_API_ROUTER="tests.test_open_writes.open_router",
    SILENCED_SYSTEM_CHECKS=["karni.W102"],
)
def test_silenced_through_django() -> None:
    """`manage.py check` drops a message whose id is in SILENCED_SYSTEM_CHECKS."""
    messages = check_open_writes()
    assert messages and all(message.is_silenced() for message in messages)


@override_settings(KARNI_API_ROUTER="nowhere.get_router")
def test_an_unimportable_router_is_left_to_e128() -> None:
    assert check_open_writes() == []


def _staff_only(request: Any) -> bool:
    return bool(getattr(request.user, "is_staff", False))


@pytest.mark.parametrize(
    ("predicate", "open_"),
    [
        (Authenticated(), True),
        (Public(), True),
        (Owned("organizer") | Authenticated(), True),
        (Authenticated() & Where(_staff_only), True),
        (HasRole("staff"), False),
        (Granted(), False),
        (Owned("organizer"), False),
        (Can("testapp.event:change"), False),
        (Authenticated() & HasRole("editor"), False),
        (Authenticated() & Owned("organizer"), False),
        (Authenticated() & (HasRole("a") | Owned("organizer")), False),
        (Owned("organizer") | HasRole("staff"), False),
        (Owned("organizer", bypass=HasRole("staff")), False),
        (Owned("organizer", bypass=Authenticated()), True),
        (Authenticated() & Owned("organizer", bypass=Public()), True),
        (Where(_staff_only), False),
    ],
)
def test_admits_every_user(predicate: Predicate, open_: bool) -> None:
    assert admits_every_user(predicate) is open_
