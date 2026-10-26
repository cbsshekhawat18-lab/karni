"""Shared fixtures: a clean cache and synced roles for every test, and the people who edit."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from karni.accounts.permissions import assign_role
from karni.accounts.roles import sync_roles


@pytest.fixture(autouse=True)
def _clean_cache() -> Iterator[None]:
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def roles(db: None) -> None:
    sync_roles()


def make_user(email: str, *roles: str, staff: bool = False, superuser: bool = False) -> Any:
    model = get_user_model()
    if superuser:
        return model.objects.create_superuser(email=email, password="s3cret-pass-123")
    user = model.objects.create_user(email=email, password="s3cret-pass-123", is_staff=staff)
    for slug in roles:
        assign_role(user, slug)
    return user


@pytest.fixture
def editor(roles: None) -> Any:
    return make_user("editor@example.com", "editor", staff=True)


@pytest.fixture
def owner(db: None) -> Any:
    return make_user("owner@example.com", superuser=True)
