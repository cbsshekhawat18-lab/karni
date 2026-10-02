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
an anonymous one.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model

from karni.api import Access, Authenticated, BaseViewSet, HasRole, Public
from tests.testapp.models import Event, Tag, Venue


class EventViewSet(BaseViewSet):
    """The contract's target API: full CRUD from three declared attributes."""

    model = Event
    access = Access(read=Public(), write=Authenticated())
    search_fields = ["title"]


class VenueViewSet(BaseViewSet):
    """Bare declaration — everything comes from conventions and settings."""

    model = Venue
    access = Access(read=Public(), write=Authenticated())


class TagViewSet(BaseViewSet):
    """Kept off the auto-router; tests register it explicitly when needed."""

    model = Tag
    access = Access(read=Public(), write=Authenticated())
    auto_register = False


class OrganizerViewSet(BaseViewSet):
    """Routes the user model (prefix ``users``) for relation-target lookups."""

    model = get_user_model()
    access = Access(read=Authenticated(), write=HasRole("staff"))
