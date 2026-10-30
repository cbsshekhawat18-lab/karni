"""Viewsets the router autodiscovers for the api test suite.

``EventViewSet`` is the contract's target proof — ``model``, ``access`` and
``search_fields`` and nothing else; its declaration makes reads explicitly
public and writes authenticated (ADR 0001 Q2.1: no viewset without
``access``). ``VenueViewSet`` shows the bare-minimum declaration,
``TagViewSet`` opts out of autodiscovery (router tests register it
explicitly when they need a Tag route), and ``OrganizerViewSet`` routes the
user model so relation fields pointing at it resolve an ``x-karni-relation``
resource in the schema tests (amendment B13) — users are readable by
authenticated callers only, so ``?expand=organizer`` never shows an email to
an anonymous one. ``RegionViewSet``, ``CategoryViewSet`` and
``ProductViewSet`` serve the tree models (tests/tree/): the tree endpoints
come from the model alone.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model

from karni.api import Access, Authenticated, BaseViewSet, HasRole, Public
from tests.testapp.models import Category, Event, LooseSlot, Product, Region, Slot, Tag, Venue


# karni: allow(public-integer-key): the test API is public on purpose, with either key type
class EventViewSet(BaseViewSet):
    """The contract's target API: full CRUD from three declared attributes."""

    model = Event
    access = Access(read=Public(), write=Authenticated())
    search_fields = ["title"]


# karni: allow(public-integer-key): the test API is public on purpose, with either key type
class VenueViewSet(BaseViewSet):
    """Bare declaration — everything comes from conventions and settings."""

    model = Venue
    access = Access(read=Public(), write=Authenticated())


# karni: allow(public-integer-key): the test API is public on purpose, with either key type
class TagViewSet(BaseViewSet):
    """Kept off the auto-router; tests register it explicitly when needed."""

    model = Tag
    access = Access(read=Public(), write=Authenticated())
    auto_register = False


class OrganizerViewSet(BaseViewSet):
    """Routes the user model (prefix ``users``) for relation-target lookups."""

    model = get_user_model()
    access = Access(read=Authenticated(), write=HasRole("staff"))


class SlotViewSet(BaseViewSet):
    model = Slot
    access = Access(read=Authenticated(), write=Authenticated())


class LooseSlotViewSet(BaseViewSet):
    model = LooseSlot
    access = Access(read=Authenticated(), write=Authenticated())


# karni: allow(public-integer-key): the test API is public on purpose, with either key type
class RegionViewSet(BaseViewSet):
    """A tree model: tree/, children/, ancestors/ and move/ with no declaration."""

    model = Region
    access = Access(read=Public(), write=Authenticated())
    search_fields = ["name"]


class CategoryViewSet(BaseViewSet):
    """An ordered tree, readable by signed-in users and changed by staff."""

    model = Category
    access = Access(read=Authenticated(), write=HasRole("staff"))


# karni: allow(public-integer-key): the test API is public on purpose, with either key type
class ProductViewSet(BaseViewSet):
    """Points at both trees: its category and regions carry x-karni-tree."""

    model = Product
    access = Access(read=Public(), write=Authenticated())
