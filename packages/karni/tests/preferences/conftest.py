"""Fixtures of the preferences suite: roles, its URLconf, users holding them."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.test import override_settings

from karni.accounts.permissions import assign_role
from karni.accounts.roles import sync_roles
from tests.people.conftest import make_user

ROLES = {
    "admin": {"system": True, "grants": {"*": "all"}},
    # Changes the business's details only.
    "office": {"grants": {"preferences.details:change": "all"}},
    # Changes the help desk's section (by role) and nothing else.
    "desk-lead": {"grants": {"helpdeskapp.ticket:view": "all"}},
    "customer": {"grants": {"helpdeskapp.ticket:view": "own"}},
}


@pytest.fixture(autouse=True)
def _preferences_api() -> Iterator[None]:
    with override_settings(KARNI_ROLES=ROLES, ROOT_URLCONF="tests.preferences.urls"):
        sync_roles()
        yield


def user(email: str, *roles: str) -> Any:
    found = make_user(email)
    for role in roles:
        assign_role(found, role)
    return found


@pytest.fixture
def admin() -> Any:
    return user("admin@example.com", "admin")


@pytest.fixture
def office() -> Any:
    return user("office@example.com", "office")


@pytest.fixture
def lead() -> Any:
    return user("lead@example.com", "desk-lead")


@pytest.fixture
def customer() -> Any:
    return user("customer@example.com", "customer")
