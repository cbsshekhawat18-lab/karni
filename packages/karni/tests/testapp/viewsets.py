"""Viewsets the router autodiscovers for the api test suite.

``EventViewSet`` is byte-for-byte the contract's target proof — ``model`` plus
``search_fields`` and nothing else. ``VenueViewSet`` shows the bare-minimum
declaration, ``TagViewSet`` opts out of autodiscovery (router tests register
it explicitly when they need a Tag route), and ``OrganizerViewSet`` routes the
user model so relation fields pointing at it resolve an ``x-karni-relation``
resource in the schema tests (amendment B13).
"""

from __future__ import annotations

from django.contrib.auth import get_user_model

from karni.api import BaseViewSet
from tests.testapp.models import Event, Tag, Venue


class EventViewSet(BaseViewSet):
    """The contract's target API: full CRUD from two declared attributes."""

    model = Event
    search_fields = ["title"]


class VenueViewSet(BaseViewSet):
    """Bare declaration — everything comes from conventions and settings."""

    model = Venue


class TagViewSet(BaseViewSet):
    """Kept off the auto-router; tests register it explicitly when needed."""

    model = Tag
    auto_register = False


class OrganizerViewSet(BaseViewSet):
    """Routes the user model (prefix ``users``) for relation-target lookups."""

    model = get_user_model()
