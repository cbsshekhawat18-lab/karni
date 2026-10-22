"""Fixtures for ``tests/why``: roles, users of every kind, rows of every kind, the router."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import override_settings
from django.utils import timezone

from karni.accounts.permissions import assign_role
from karni.accounts.roles import sync_roles
from karni.vetoes import register_veto, unregister_veto
from tests.testapp.models import Customer, Event, Venue
from tests.why.routes import ROLES, ROUTER, no_reader_deletes


@pytest.fixture(autouse=True)
def _why_world(db: Any) -> Iterator[None]:
    with override_settings(KARNI_ROLES=ROLES, KARNI_API_ROUTER=ROUTER):
        sync_roles()
        register_veto(no_reader_deletes, name="tests.why.no_reader_deletes")
        try:
            yield
        finally:
            unregister_veto("tests.why.no_reader_deletes")


def _user(email: str, *roles: str, **flags: Any) -> Any:
    user = get_user_model().objects.create_user(
        email=email, password="a-strong-password-123", **flags
    )
    for role in roles:
        assign_role(user, role)
    return user


@pytest.fixture
def world() -> SimpleNamespace:
    """Users and rows: every case the matrix crosses."""
    arena = Venue.objects.create(name="Arena", city="Pune")
    hall = Venue.objects.create(name="Hall", city="Jaipur")
    alice = _user("alice@example.com", "organizer")
    bob = _user("bob@example.com", "organizer")
    manager = _user("manager@example.com", "venue_manager")
    manager.venue = arena  # the related:venue scope reads user.venue
    users = {
        "anonymous": AnonymousUser(),
        "alice": alice,
        "bob": bob,
        "staff": _user("staff@example.com", "staff"),
        "reader": _user("reader@example.com", "reader"),
        "manager": manager,
        "nobody": _user("nobody@example.com"),
        "root": _user("root@example.com", is_superuser=True, is_staff=True),
    }
    now = timezone.now()

    def event(title: str, **fields: Any) -> Event:
        return Event.objects.create(title=title, starts_at=now, **fields)

    rows = {
        "alice-draft": event("Alice draft", organizer=alice, venue=arena),
        "alice-published": event(
            "Alice published", organizer=alice, venue=hall, status=Event.Status.PUBLISHED
        ),
        "bob-draft": event("Bob draft", organizer=bob, venue=arena),
        "bob-published": event(
            "Bob published", organizer=bob, venue=hall, status=Event.Status.PUBLISHED
        ),
        "orphan": event("Orphan", venue=None),
    }
    gone = event("Deleted", organizer=alice, venue=arena, status=Event.Status.PUBLISHED)
    gone.delete()  # soft delete: the model scope hides it from everyone
    rows["deleted"] = gone
    customers = {
        "acme": Customer.objects.create(
            name="Acme", phone="+1 555 0100", internal_note="pays late", salary=Decimal("10")
        )
    }
    return SimpleNamespace(users=users, rows=rows, customers=customers, venues=(arena, hall))
