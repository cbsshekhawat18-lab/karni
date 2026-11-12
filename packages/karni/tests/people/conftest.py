"""Fixtures of the people suite: roles, the people API's router, and a small family of rows."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from karni.accounts.roles import sync_roles
from karni.people.models import Address, Membership, Organisation, Person
from tests.helpdeskapp.models import Note, SupportProfile, Ticket
from tests.loyaltyapp.models import LoyaltyCard, Visit

ROLES = {
    # The family's admin: everything, and the explicit actions written out.
    "admin": {
        "system": True,
        "grants": {"*": "all", "people.*:merge": "all", "people.person:erase": "all"},
    },
    # Everything but the explicit actions: "*" never reaches merge or erase.
    "staff": {"system": True, "grants": {"*": "all"}},
    # A part's role that reads people and merges them (a CRM's manager).
    "desk": {
        "grants": {
            "people.person:view": "all",
            "people.person:merge": "all",
            "people.organisation:view": "all",
        }
    },
    # Reads people, nothing else.
    "viewer": {"grants": {"people.person:view": "all"}},
    # The family's default role: what is their own.
    "customer": {"grants": {"*": "own"}},
}


@pytest.fixture(autouse=True)
def _people_api() -> Iterator[None]:
    with override_settings(
        KARNI_ROLES=ROLES,
        ROOT_URLCONF="tests.people.urls",
        KARNI_API_ROUTER="tests.people.urls.get_router",
    ):
        sync_roles()
        yield


def make_user(email: str, *, verified: bool = True, **fields: Any) -> Any:
    """A user with ``email`` (verified unless said otherwise)."""
    return get_user_model().objects.create_user(
        email=email, password="karni-password", email_verified=verified, **fields
    )


@pytest.fixture
def family() -> dict[str, Any]:
    """Two people known to both parts, the same human twice: Ana's two records."""
    org = Organisation.objects.create(
        name="Fernwood Design", domain="https://www.Fernwood.example/"
    )
    other = Organisation.objects.create(name="Riverbend Books", domain="riverbend.example")
    keep = Person.objects.create(given_name="Ana", family_name="Lima", email="ana@example.com")
    drop = Person.objects.create(
        given_name="Ana", family_name="Lima", email="ana+club@example.com", phone="+44 20 7946 0001"
    )
    LoyaltyCard.objects.create(person=keep, points=10, nickname="")
    LoyaltyCard.objects.create(person=drop, points=5, nickname="Annie")
    for day in (1, 2):
        Visit.objects.create(person=keep, visited_on=dt.date(2026, 10, day), spent=Decimal("12.50"))
    Visit.objects.create(person=drop, visited_on=dt.date(2026, 11, 3), spent=Decimal("30.00"))
    SupportProfile.objects.create(person=keep, plan="basic")
    SupportProfile.objects.create(person=drop, plan="priority")
    Ticket.objects.create(
        person=keep, subject="Wifi", contact_name="Ana Lima", contact_email="ana@example.com"
    )
    for subject in ("Locker", "Invoice"):
        Ticket.objects.create(
            person=drop,
            subject=subject,
            contact_name="Ana L.",
            contact_email="ana+club@example.com",
        )
    Ticket.objects.filter(subject="Invoice").update(status="closed")
    Note.objects.create(subject=drop, text="Prefers mornings.")
    Membership.objects.create(person=keep, organisation=org, title="")
    Membership.objects.create(person=drop, organisation=org, title="Owner")
    Membership.objects.create(person=drop, organisation=other, title="Buyer")
    Address.objects.create(
        person=keep, line1="1 Mill Lane", city="Leeds", country="GB", is_default_billing=True
    )
    Address.objects.create(
        person=drop, line1="9 Park Avenue", city="Leeds", country="GB", is_default_billing=True
    )
    return {"keep": keep, "drop": drop, "org": org, "other": other}
