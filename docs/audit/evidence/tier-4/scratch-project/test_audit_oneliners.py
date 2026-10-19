"""Tier 4 audit, item 6: the one-liners from karni.testing and karni.accounts."""

from __future__ import annotations

import pytest
from karni.accounts.roles import requires
from karni.middleware import current_user
from karni.testing import APITestCase, assert_crud, assert_isolated, client_as, user_with_roles
from rest_framework.exceptions import PermissionDenied

from events.models import Venue
from events.viewsets import CanVenueViewSet, EventViewSet, LeakyEventViewSet


class OneLinerTests(APITestCase):
    def test_assert_crud_one_line(self) -> None:
        self.assert_crud(EventViewSet, "organizer")

    def test_assert_isolated_one_line(self) -> None:
        self.assert_isolated(EventViewSet, "organizer")

    def test_assert_isolated_catches_the_leaky_viewset(self) -> None:
        """DELIBERATELY FAILING: LeakyEventViewSet widens the read scope — the message must say so."""
        self.assert_isolated(LeakyEventViewSet, "organizer")


# plain pytest style, one line each
def test_assert_crud_plain_pytest(db):
    assert_crud(EventViewSet, "organizer")


def test_assert_isolated_plain_pytest(db):
    assert_isolated(EventViewSet, "organizer")


# docs/accounts.md: user.can(...), @requires(...), Can(...)
@requires("events.venue:change")
def rename_venue(venue: Venue, name: str) -> Venue:
    venue.name = name
    venue.save()
    return venue


def test_user_can_one_liner(db):
    assert user_with_roles("staff").can("events.venue:change") is True      # staff: "*": "all"
    assert user_with_roles().can("events.venue:change") is False            # no roles: nothing
    venue = Venue.objects.create(name="v", city="c")
    assert user_with_roles("staff").can("change", obj=venue) is True


def test_requires_one_liner(db):
    venue = Venue.objects.create(name="v", city="c")
    with current_user(user_with_roles("staff")):
        assert rename_venue(venue, "renamed").name == "renamed"
    with current_user(user_with_roles()), pytest.raises(PermissionDenied) as excinfo:
        rename_venue(venue, "nope")
    print(f"\n@requires denial: {excinfo.value.detail!r} code={excinfo.value.get_codes()!r}")


def test_can_predicate_one_liner(db):
    Venue.objects.create(name="v", city="c")
    assert client_as("staff").get("/api/can-venues/").status_code == 200
    assert client_as().get("/api/can-venues/").status_code == 403
    assert client_as("staff").get("/api/can-venues/").json()["count"] == 1
    assert CanVenueViewSet.access.read is not None
