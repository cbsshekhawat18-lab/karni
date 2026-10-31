"""Shared world of the navigation suite: a product catalog menu, its roles and users."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from pytest_django import Settings

from karni.accounts.permissions import assign_role
from karni.accounts.roles import sync_roles
from karni.navigation.models import NavItem

#: The menu of the suite, as KARNI_NAVIGATION writes it.
MENU: list[dict[str, Any]] = [
    {"label": "Home", "route": "/", "icon": "home", "requires": "public"},
    {
        "label": "Catalog",
        "icon": "box",
        "children": [
            {"label": "Products", "route": "/products", "requires": "testapp.product:view"},
            {
                "label": "Categories",
                "route": "/categories",
                "requires": "testapp.category:view",
                "order": -1,
            },
        ],
    },
    {"label": "Regions", "route": "/regions", "icon": "map", "requires": "testapp.region:view"},
    {"label": "Events", "route": "/events", "requires": "testapp.event:*"},
    {"label": "Account", "route": "/account"},
]

ROLES = {
    "catalog_editor": {"grants": {"testapp.product:*": "all", "testapp.category:view": "all"}},
    "organizer": {"grants": {"testapp.event:view": "own"}},
    "ops": {"system": True, "grants": {"*": "all"}},
}


@pytest.fixture
def roles(settings: Settings) -> None:
    """The suite's roles, synced. Through ``settings``, so every override unwinds in order."""
    settings.KARNI_ROLES = ROLES
    sync_roles()


def make_user(email: str, *roles: str, **flags: Any) -> Any:
    user = get_user_model().objects.create_user(email=email, password="s3cret-pass-123", **flags)
    for slug in roles:
        assign_role(user, slug)
    return user


def fresh(user: Any) -> Any:
    """The same user as a new instance: what the next request sees (no cached grants)."""
    return get_user_model().objects.get(pk=user.pk)


def store(menu: list[dict[str, Any]], parent: NavItem | None = None) -> None:
    """``menu`` as NavItem rows, siblings in the order the settings source sorts them."""
    ranked = sorted(enumerate(menu), key=lambda pair: (pair[1].get("order", 0), pair[0]))
    for _index, item in ranked:
        row = NavItem.objects.create(
            label=item["label"],
            route=item.get("route", ""),
            icon=item.get("icon", ""),
            requires=item.get("requires", "authenticated"),
            parent=parent,
        )
        store(item.get("children", []), row)
