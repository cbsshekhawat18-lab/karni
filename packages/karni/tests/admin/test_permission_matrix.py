"""The permission matrix and effective-permissions admin pages (ADR 0002, P5)."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission as DjangoPermission
from django.contrib.contenttypes.models import ContentType
from django.test import Client, override_settings
from django.urls import reverse

from karni.accounts.models import Role, RolePermission
from karni.accounts.permissions import assign_role
from karni.accounts.roles import sync_roles

pytestmark = pytest.mark.django_db

VIEW = "testapp.event:view"
APPROVE = "testapp.event:approve"

PROJECT_ROLES = {
    "organizer": {"grants": {VIEW: "own", "testapp.event:add": "all"}},
    "ops": {"system": True, "grants": {"*": "all"}},
}


@pytest.fixture(autouse=True)
def _synced() -> Any:
    with override_settings(KARNI_ROLES=PROJECT_ROLES):
        sync_roles()
        yield


def _staff(email: str, *roles: str, superuser: bool = False) -> Any:
    model = get_user_model()
    if superuser:
        return model.objects.create_superuser(email=email, password="a-strong-password-123")
    user = model.objects.create_user(email=email, password="a-strong-password-123", is_staff=True)
    for role in roles:
        assign_role(user, role)
    user.user_permissions.add(
        *DjangoPermission.objects.filter(
            content_type__in=[
                ContentType.objects.get_for_model(Role),
                ContentType.objects.get_for_model(model),
            ]
        )
    )
    return user


def _client(user: Any) -> Client:
    client = Client()
    client.force_login(user)
    return client


MATRIX_URL = reverse("admin:karni_accounts_role_permission_matrix")
EFFECTIVE_URL = reverse("admin:karni_accounts_role_effective_permissions")


def test_the_role_changelist_links_to_the_matrix() -> None:
    page = _client(_staff("root@example.com", superuser=True)).get(
        reverse("admin:karni_accounts_role_changelist")
    )
    assert page.status_code == 200
    assert MATRIX_URL in page.content.decode() and EFFECTIVE_URL in page.content.decode()


def test_the_matrix_page_shows_one_select_per_cell() -> None:
    page = _client(_staff("root@example.com", superuser=True)).get(MATRIX_URL)
    assert page.status_code == 200
    body = page.content.decode()
    assert 'name="cell:organizer:testapp.event:view"' in body
    assert 'name="cell:organizer:testapp.event:approve"' in body
    assert "Review changes" in body and "data-bulk-role" in body and "data-bulk-model" in body
    # A system role's declared cell is locked.
    locked = body.split('name="cell:ops:testapp.event:view"', 1)[1].split("</select>", 1)[0]
    assert "disabled" in body.split('name="cell:ops:testapp.event:view"', 1)[0][-200:] + locked
    assert "sessions.session" not in body


def test_changes_are_confirmed_before_they_are_saved() -> None:
    client = _client(_staff("root@example.com", superuser=True))
    review = client.post(
        MATRIX_URL,
        {"cell:organizer:testapp.event:view": "own", "cell:organizer:testapp.event:approve": "all"},
    )
    assert review.status_code == 200
    body = review.content.decode()
    assert "Confirm permission changes" in body and "Apply 1 change" in body
    assert 'name="change:organizer:testapp.event:approve" value="all"' in body
    assert not RolePermission.objects.filter(role__slug="organizer", permission__action="approve")
    applied = client.post(
        MATRIX_URL, {"confirm": "1", "change:organizer:testapp.event:approve": "all"}, follow=True
    )
    assert applied.status_code == 200 and "1 grant changed." in applied.content.decode()
    row = RolePermission.objects.get(role__slug="organizer", permission__action="approve")
    assert (row.scope, row.origin) == ("all", "matrix")
    # The page now shows the grant and its origin, and the audit trail below it.
    body = client.get(MATRIX_URL).content.decode()
    assert "set here" in body and "root@example.com" in body and "testapp.event:approve" in body


def test_a_refused_change_is_shown_and_nothing_is_saved() -> None:
    client = _client(_staff("root@example.com", superuser=True))
    review = client.post(
        MATRIX_URL,
        {"cell:ops:testapp.event:view": "", "cell:organizer:testapp.event:approve": "all"},
    )
    body = review.content.decode()
    assert (
        "Refused" in body and "system role" in body and "Apply" not in body.split("Changes", 1)[1]
    )
    assert not RolePermission.objects.filter(role__slug="organizer", permission__action="approve")
    # Confirming anyway (a tampered form) is refused the same way.
    forced = client.post(MATRIX_URL, {"confirm": "1", "change:ops:testapp.event:view": ""})
    assert forced.status_code == 200 and "Refused" in forced.content.decode()
    assert (
        RolePermission.objects.get(
            role__slug="ops", permission__action="view", permission__content_type__model="event"
        ).scope
        == "all"
    )


def test_nothing_changed_goes_straight_back() -> None:
    client = _client(_staff("root@example.com", superuser=True))
    response = client.post(MATRIX_URL, {"cell:organizer:testapp.event:view": "own"}, follow=True)
    assert "Nothing changed." in response.content.decode()


def test_viewing_and_editing_follow_the_grants() -> None:
    member = _staff("o@example.com", "organizer")  # no rolepermission grant at all
    assert _client(member).get(MATRIX_URL).status_code == 403
    ops = _staff("ops@example.com", "ops")
    page = _client(ops).get(MATRIX_URL)
    assert page.status_code == 200 and "Review changes" in page.content.decode()


def test_effective_permissions_page_picks_a_user() -> None:
    _staff("o@example.com", "organizer")
    client = _client(_staff("root@example.com", superuser=True))
    empty = client.get(EFFECTIVE_URL)
    assert empty.status_code == 200 and "Pick a user" in empty.content.decode()
    page = client.get(EFFECTIVE_URL, {"user": "o@example.com"})
    body = page.content.decode()
    assert "o@example.com" in body and "roles:</span> organizer" not in body
    assert "role organizer grants own (declared)" in body
    assert "testapp.event" in body
    missing = client.get(EFFECTIVE_URL, {"user": "nobody@example.com"})
    assert "No user matches" in missing.content.decode()


def test_effective_permissions_from_the_user_change_page() -> None:
    member = _staff("o@example.com", "organizer")
    client = _client(_staff("root@example.com", superuser=True))
    change = client.get(reverse("admin:karni_accounts_user_change", args=[member.pk]))
    url = reverse("admin:karni_accounts_user_effective_permissions", args=[member.pk])
    assert url in change.content.decode()
    page = client.get(url)
    assert (
        page.status_code == 200 and "role organizer grants own (declared)" in page.content.decode()
    )
    # Through the user admin the row scope applies: no grant on users, no row (404).
    assert _client(member).get(url).status_code == 404
    # The picker page shows one's own permissions without any matrix grant; others' need it.
    own = _client(member).get(EFFECTIVE_URL, {"user": member.email})
    assert own.status_code == 200 and "role organizer grants own (declared)" in own.content.decode()
    other = _staff("x@example.com", "organizer")
    assert _client(member).get(EFFECTIVE_URL, {"user": other.email}).status_code == 403
