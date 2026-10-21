"""A router of row-scoped resources for the hidden-row suite (``tests/testing/test_hidden.py``).

Every resource here lets a user *list* it but scopes which rows they see,
so a denial is a row-scope denial (404), never a role-level one (403):

* ``events`` — ``Granted()``: an ``own`` grant for organizers, ``all`` for staff;
* ``venues`` — readable when in Berlin (or by staff), writable by anyone signed
  in, with the reverse ``events`` relation expandable (the hidden event reached
  from another resource);
* ``tags`` — readable by taggers only (a to-many expand target);
* ``prices`` — audited (``/history/``), readable when priced in EUR.

Used with ``override_settings(ROOT_URLCONF=__name__, KARNI_API_ROUTER=
"tests.testing.hidden_urls.get_router")``; nothing here sits in an
autodiscovered module, so the project-wide schema snapshot never sees it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.contrib import admin
from django.db.models import Q
from django.urls import include, path

from karni.api import Access, Authenticated, BaseViewSet, Granted, HasRole, Where
from karni.api.routers import KarniRouter
from tests.testapp.models import Event, Price, Tag, Venue


def _in_berlin(request: Any) -> Q:
    return Q(city="Berlin")


def _in_euro(request: Any) -> Q:
    return Q(currency="EUR")


class HiddenEventViewSet(BaseViewSet):
    """Whatever the roles grant: organizers reach their own events (an ``own`` grant)."""

    model = Event
    access = Granted()
    search_fields = ("title",)


class HiddenVenueViewSet(BaseViewSet):
    """Berlin venues for everyone signed in; every venue for staff."""

    model = Venue
    access = Access(read=Where(_in_berlin) | HasRole("staff"), write=Authenticated())
    search_fields = ("name",)
    expandable_fields = {"events": "events"}


class HiddenTagViewSet(BaseViewSet):
    model = Tag
    access = Access(read=HasRole("tagger", "staff"), write=HasRole("tagger"))


class HiddenPriceViewSet(BaseViewSet):
    """Audited (``class Karni: audit = True``), so ``/history/`` is routed."""

    model = Price
    access = Access(read=Where(_in_euro) | HasRole("staff"), write=Authenticated())
    search_fields = ("note",)


ROUTES = {
    "events": HiddenEventViewSet,
    "venues": HiddenVenueViewSet,
    "tags": HiddenTagViewSet,
    "prices": HiddenPriceViewSet,
}

ROLES = {
    "staff": {"system": True, "grants": {"*": "all"}},
    "organizer": {"grants": {"testapp.event:*": "own", "testapp.venue:view": "all"}},
    "planner": {"grants": {"testapp.event:*": "own"}},
}
"""``KARNI_ROLES`` for the suite (``sync_roles()`` writes them).

Both organizers and planners reach their own events; in the admin an
organizer may view every venue, a planner none.
"""


@dataclass
class World:
    """Alice's rows and the ones hidden from her (``make_world``)."""

    alice: Any
    bob: Any
    berlin: Venue  # readable by everyone signed in
    rome: Venue  # hidden from Alice: not in Berlin
    tag: Tag  # hidden from Alice: she is no tagger
    mine: Event  # Alice's, in Rome, tagged
    theirs: Event  # Bob's, in Berlin: hidden from Alice
    euro: Price  # readable
    pound: Price  # hidden: not in EUR


def make_world() -> World:
    """The suite's rows (call inside ``override_settings(KARNI_ROLES=ROLES)`` + ``sync_roles``)."""
    from django.utils import timezone

    from karni.testing import user_with_roles

    alice = user_with_roles("organizer")
    bob = user_with_roles("organizer")
    berlin = Venue.objects.create(name="Arena", city="Berlin")
    rome = Venue.objects.create(name="Colosseo", city="Rome")
    tag = Tag.objects.create(name="secret")
    mine = Event.objects.create(
        title="Alice keynote", starts_at=timezone.now(), organizer=alice, venue=rome
    )
    mine.tags.add(tag)
    theirs = Event.objects.create(
        title="Bob zeppelin", starts_at=timezone.now(), organizer=bob, venue=berlin
    )
    euro = Price.objects.create(amount=1, currency="EUR", note="open euro")
    pound = Price.objects.create(amount=2, currency="GBP", note="sterling secret")
    return World(alice, bob, berlin, rome, tag, mine, theirs, euro, pound)


router = KarniRouter()
for prefix, viewset in ROUTES.items():
    router.register(prefix, viewset, basename=f"hidden-{prefix}")


def get_router() -> KarniRouter:
    return router


urlpatterns = [path("admin/", admin.site.urls), path("api/", include(router.urls))]
