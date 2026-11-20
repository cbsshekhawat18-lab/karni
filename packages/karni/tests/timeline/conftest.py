"""Fixtures of the timeline suite: roles, its URLconf, two people and their parts' rows."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.test import override_settings

from karni.accounts.roles import sync_roles
from karni.people.models import Organisation, Person
from tests.people.conftest import make_user

ROLES = {
    "admin": {"system": True, "grants": {"*": "all"}},
    # A help desk agent: every ticket and person, no visits.
    "agent": {
        "grants": {
            "helpdeskapp.ticket:view": "all",
            "people.person:view": "all",
            "people.organisation:view": "all",
        }
    },
    # The family's default role: what is their own.
    "customer": {"grants": {"*": "own"}},
}


@pytest.fixture(autouse=True)
def _timeline_api() -> Iterator[None]:
    with override_settings(
        KARNI_ROLES=ROLES,
        ROOT_URLCONF="tests.timeline.urls",
        KARNI_API_ROUTER="tests.timeline.urls.get_router",
    ):
        sync_roles()
        yield


def with_role(user: Any, *roles: str) -> Any:
    from karni.accounts.permissions import assign_role

    for role in roles:
        assign_role(user, role)
    return user


@pytest.fixture
def cast() -> dict[str, Any]:
    """Two customers with accounts and people, an agent, an admin, one organisation."""
    org = Organisation.objects.create(name="Harbour Rowing Club", domain="harbour.example")
    ines_user = with_role(make_user("ines@example.com"), "customer")
    omar_user = with_role(make_user("omar@example.com"), "customer")
    ines = Person.objects.create(
        given_name="Ines",
        family_name="Duarte",
        email="ines@example.com",
        user=ines_user,
        organisation=org,
    )
    omar = Person.objects.create(
        given_name="Omar", family_name="Haddad", email="omar@example.com", user=omar_user
    )
    agent = with_role(make_user("agent@example.com"), "agent")
    admin = with_role(make_user("admin@example.com", is_staff=True), "admin")
    return {
        "org": org,
        "ines": ines,
        "omar": omar,
        "ines_user": ines_user,
        "omar_user": omar_user,
        "agent": agent,
        "admin": admin,
    }
