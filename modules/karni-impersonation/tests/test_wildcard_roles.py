"""A wildcard role never holds ``impersonate``: only a grant that names it does.

Every scaffold carries ``user`` and ``customer`` (``"*": "own"``) and
``staff`` (``"*": "all"``). Before ``Karni.explicit_actions`` those wildcards
reached the module's ``impersonate`` action, so any signed-in user could act
as another user of the same grants.
"""

from __future__ import annotations

from typing import Any

import pytest
from karni.accounts.models import Permission, Role, RolePermission
from karni.accounts.roles import sync_roles, user_can
from rest_framework.test import APIClient

from karni_impersonation.services import PERMISSION
from tests.conftest import make_user

pytestmark = pytest.mark.django_db

#: The roles a scaffold declares by default (karni.conf.base), plus the
#: support role this module's README asks for.
WILDCARD_ROLES = {
    "staff": {"name": "Staff", "system": True, "grants": {"*": "all"}},
    "user": {"name": "User", "grants": {"*": "own"}},
    "customer": {"name": "Customer", "grants": {"*": "own"}},
    "sessions": {
        "name": "Sessions",
        "grants": {"karni_impersonation.impersonationsession:*": "all"},
    },
    "support": {
        "name": "Support",
        "grants": {"*": "own", PERMISSION: "all", "karni_accounts.user:view": "all"},
    },
}


@pytest.fixture(autouse=True)
def _jwt(settings: Any) -> None:
    settings.KARNI_AUTH_MODE = "jwt"
    settings.KARNI_ROLES = WILDCARD_ROLES
    sync_roles()


def _start(actor: Any, target: Any) -> Any:
    client = APIClient()
    client.force_authenticate(actor)
    return client.post(
        "/api/impersonation-sessions/start/",
        {"user": target.email, "reason": "ticket"},
        format="json",
    )


@pytest.mark.parametrize("role", ["user", "customer", "staff", "sessions"])
def test_a_wildcard_role_cannot_impersonate(role: str) -> None:
    carol = make_user("carol@example.com", role)
    dave = make_user("dave@example.com", role)
    assert not user_can(carol, PERMISSION)
    answer = _start(carol, dave)
    assert answer.status_code == 403, answer.content
    assert PERMISSION in str(answer.json())


def test_a_role_that_names_the_grant_may() -> None:
    agent = make_user("agent@example.com", "support")
    dave = make_user("dave@example.com", "customer")
    assert user_can(agent, PERMISSION)
    answer = _start(agent, dave)
    assert answer.status_code == 201, answer.content
    assert answer.json()["access"]


def test_a_later_wildcard_does_not_overwrite_the_named_grant(settings: Any) -> None:
    settings.KARNI_ROLES = {
        "support": {"grants": {PERMISSION: "all", "*": "own"}},
    }
    sync_roles()
    row = RolePermission.objects.get(role__slug="support", permission__action="impersonate")
    assert row.scope == "all"


def test_the_next_sync_takes_back_a_grant_an_older_karni_synced() -> None:
    """Karni 0.4 synced ``impersonate`` into every wildcard role. The next sync removes it."""
    permission = Permission.objects.get(
        content_type__app_label="karni_impersonation", action="impersonate"
    )
    for slug in ("user", "customer", "staff"):
        RolePermission.objects.create(
            role=Role.objects.get(slug=slug), permission=permission, scope="all"
        )
    carol = make_user("carol@example.com", "customer")
    assert user_can(carol, PERMISSION)
    sync_roles()
    assert not RolePermission.objects.filter(
        permission=permission, role__slug__in=["user", "customer", "staff"]
    ).exists()
    carol = type(carol).objects.get(pk=carol.pk)  # a fresh instance: grants are cached per user
    assert _start(carol, make_user("dave@example.com", "customer")).status_code == 403
