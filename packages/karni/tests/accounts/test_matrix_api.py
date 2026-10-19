"""The permission matrix as an API (ADR 0002, P5): the same functions, over HTTP."""

from __future__ import annotations

from typing import Any

import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from karni.accounts.models import RolePermission
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


def _user(django_user_model: Any, email: str, *role_slugs: str) -> Any:
    user = django_user_model.objects.create_user(email=email, password="s3cret-pass-123")
    for slug in role_slugs:
        assign_role(user, slug)
    return user


def _client(user: Any | None = None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


MATRIX_URL = reverse("karni-accounts-permission-matrix")
EFFECTIVE_URL = reverse("karni-accounts-effective-permissions")


def test_get_the_matrix(django_user_model: Any) -> None:
    ops = _user(django_user_model, "ops@example.com", "ops")
    body = _client(ops).get(MATRIX_URL).json()
    assert {role["slug"] for role in body["roles"]} >= {"organizer", "ops"}
    event = next(model for model in body["models"] if model["label"] == "testapp.event")
    assert (
        "approve" in event["actions"]
        and {"value": "own", "label": "Own rows (organizer)"} in event["scopes"]
    )
    cell = body["grants"]["organizer"][VIEW]
    assert cell == {"scope": "own", "origin": "declared", "declared": "own", "locked": False}
    assert body["grants"]["ops"][VIEW]["locked"]


def test_viewing_needs_the_view_grant_and_a_login(django_user_model: Any) -> None:
    member = _user(django_user_model, "o@example.com", "organizer")
    assert _client(member).get(MATRIX_URL).status_code == 403
    assert _client().get(MATRIX_URL).status_code in (401, 403)


def test_dry_run_plans_without_writing(django_user_model: Any) -> None:
    ops = _user(django_user_model, "ops@example.com", "ops")
    response = _client(ops).post(
        MATRIX_URL,
        {
            "changes": [{"role": "organizer", "permission": APPROVE, "scope": "all"}],
            "dry_run": True,
        },
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["ok"] and response.json()["changes"][0]["after"] == "all"
    assert not RolePermission.objects.filter(role__slug="organizer", permission__action="approve")


def test_post_applies_and_the_matrix_reflects_it(django_user_model: Any) -> None:
    ops = _user(django_user_model, "ops@example.com", "ops")
    client = _client(ops)
    response = client.post(
        MATRIX_URL,
        {
            "changes": [
                {"role": "organizer", "permission": APPROVE, "scope": "all"},
                {"role": "organizer", "permission": VIEW, "scope": None},
            ]
        },
        format="json",
    )
    assert response.status_code == 200, response.content
    assert [(c["permission"], c["after"]) for c in response.json()["changes"]] == [
        (APPROVE, "all"),
        (VIEW, None),
    ]
    grants = client.get(MATRIX_URL).json()["grants"]["organizer"]
    assert grants[APPROVE] == {
        "scope": "all",
        "origin": "matrix",
        "declared": None,
        "locked": False,
    }
    assert grants[VIEW] == {"scope": None, "origin": "matrix", "declared": "own", "locked": False}
    restored = client.post(
        MATRIX_URL,
        {"changes": [{"role": "organizer", "permission": VIEW, "scope": "declared"}]},
        format="json",
    )
    assert (
        restored.status_code == 200 and restored.json()["changes"][0]["after_origin"] == "declared"
    )


def test_a_refused_change_is_a_400_with_e213_and_writes_nothing(django_user_model: Any) -> None:
    ops = _user(django_user_model, "ops@example.com", "ops")
    response = _client(ops).post(
        MATRIX_URL,
        {
            "changes": [
                {"role": "organizer", "permission": APPROVE, "scope": "all"},
                {"role": "ops", "permission": VIEW, "scope": None},
            ]
        },
        format="json",
    )
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "E213" and "system role" in body["refusals"][0]["reason"]
    assert not RolePermission.objects.filter(role__slug="organizer", permission__action="approve")


def test_malformed_body_is_a_validation_error(django_user_model: Any) -> None:
    ops = _user(django_user_model, "ops@example.com", "ops")
    assert (
        _client(ops).post(MATRIX_URL, {"changes": [{"role": "x"}]}, format="json").status_code
        == 400
    )


def test_effective_permissions_for_me_and_for_others(django_user_model: Any) -> None:
    member = _user(django_user_model, "o@example.com", "organizer")
    ops = _user(django_user_model, "ops@example.com", "ops")
    mine = _client(member).get(EFFECTIVE_URL)
    assert mine.status_code == 200
    body = mine.json()
    assert body["user"]["username"] == "o@example.com" and body["roles"] == ["organizer"]
    view = next(p for p in body["permissions"] if p["permission"] == VIEW)
    assert view["scope"] == "own" and view["sources"][0]["role"] == "organizer"
    other_url = reverse("karni-accounts-effective-permissions-user", args=[ops.pk])
    assert _client(member).get(other_url).status_code == 403
    assert (
        _client(member)
        .get(reverse("karni-accounts-effective-permissions-user", args=[member.pk]))
        .status_code
        == 200
    )
    theirs = _client(ops).get(
        reverse("karni-accounts-effective-permissions-user", args=[member.pk])
    )
    assert theirs.status_code == 200 and theirs.json()["user"]["id"] == str(member.pk)
    missing = reverse(
        "karni-accounts-effective-permissions-user", args=["00000000-0000-0000-0000-000000000000"]
    )
    assert _client(ops).get(missing).status_code == 404
    assert (
        _client(ops)
        .get(reverse("karni-accounts-effective-permissions-user", args=["nope"]))
        .status_code
        == 404
    )
