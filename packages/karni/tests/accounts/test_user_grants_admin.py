"""Per-user grants in the admin (experimental): the user's grants inline, the grants admin, why.

The inline is the per-user screen (add, edit, expire, delete, with
``granted_by`` filled in). *User grants* lists every grant with *Expire
selected*. Effective permissions marks each source as a role or a user grant.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, override_settings
from django.utils import timezone
from pytest_django import Settings
from rest_framework.test import APIClient

from karni.accounts import grants
from karni.accounts.models import UserGrant
from karni.accounts.permissions import assign_role
from karni.accounts.roles import sync_roles
from tests.testapp.models import Venue

pytestmark = pytest.mark.django_db

VIEW = "testapp.event:view"
APPROVE = "testapp.event:approve"
GRANTS = "/admin/karni_accounts/usergrant/"

ROLES = {
    "organizer": {"grants": {VIEW: "own", "karni_accounts.usergrant:*": "all"}},
    "ops": {"system": True, "grants": {"*": "all"}},
}


@pytest.fixture(autouse=True)
def _world(settings: Settings) -> Iterator[None]:
    settings.KARNI_USER_GRANTS = True
    with override_settings(KARNI_ROLES=ROLES):
        sync_roles()
        yield


def _user(email: str, *roles: str, **flags: Any) -> Any:
    user = get_user_model().objects.create_user(email=email, password="s3cret-pass-123", **flags)
    for slug in roles:
        assign_role(user, slug)
    return user


@pytest.fixture
def root() -> Any:
    return _user("root@example.com", is_superuser=True, is_staff=True)


def _signed_in(user: Any) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _inline(user: Any, operator: Any) -> Any:
    """The grants inline's formset class, as the user's change page builds it."""
    model_admin = site._registry[get_user_model()]
    request = RequestFactory().get("/")
    request.user = operator
    inline = next(
        i for i in model_admin.get_inline_instances(request, user) if i.model is UserGrant
    )
    return inline.get_formset(request, user)


def _formset_data(rows: list[dict[str, Any]], initial: int = 0) -> dict[str, Any]:
    data: dict[str, Any] = {
        "user_grants-TOTAL_FORMS": str(len(rows)),
        "user_grants-INITIAL_FORMS": str(initial),
        "user_grants-MIN_NUM_FORMS": "0",
        "user_grants-MAX_NUM_FORMS": "1000",
    }
    for index, row in enumerate(rows):
        for name, value in row.items():
            data[f"user_grants-{index}-{name}"] = value
    return data


# the user's page


def test_the_users_page_lists_their_grants_while_on(root: Any, settings: Settings) -> None:
    guest = _user("guest@example.com")
    grants.grant(None, guest, VIEW, "all", reason="pilot access")
    client = _signed_in(root)
    page = client.get(f"/admin/karni_accounts/user/{guest.pk}/change/").content.decode()
    assert "user_grants-TOTAL_FORMS" in page and "pilot access" in page
    settings.KARNI_USER_GRANTS = False
    page = client.get(f"/admin/karni_accounts/user/{guest.pk}/change/").content.decode()
    assert "user_grants-TOTAL_FORMS" not in page


def test_every_input_of_the_grants_inline_has_a_name(root: Any) -> None:
    """axe ``label`` (F11): the tabular rows' inputs carry their column's name."""
    from html.parser import HTMLParser

    class Inputs(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.found: dict[str, dict[str, str | None]] = {}
            self.labelled: set[str] = set()

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            found = dict(attrs)
            if tag == "label" and found.get("for"):
                self.labelled.add(str(found["for"]))
            name = str(found.get("name") or "")
            if tag in ("input", "select", "textarea") and name.startswith("user_grants-"):
                if found.get("type") != "hidden":
                    self.found[str(found.get("id") or name)] = found

    guest = _user("guest@example.com")
    grants.grant(None, guest, VIEW, "all", reason="pilot access")
    page = _signed_in(root).get(f"/admin/karni_accounts/user/{guest.pk}/change/")
    parser = Inputs()
    parser.feed(page.content.decode())
    assert "id_user_grants-0-permission" in parser.found
    unnamed = [
        key
        for key, attrs in parser.found.items()
        if not attrs.get("aria-label") and key not in parser.labelled
    ]
    assert unnamed == []
    assert parser.found["id_user_grants-0-permission"]["aria-label"] == "Permission"
    assert parser.found["id_user_grants-0-expires_at_0"]["aria-label"] == "Expires at (date)"


def test_the_inline_adds_a_grant_with_granted_by(root: Any) -> None:
    arena = Venue.objects.create(name="Arena", city="Pune")
    guest = _user("guest@example.com")
    formset_class = _inline(guest, root)
    formset = formset_class(
        data=_formset_data(
            [
                {
                    "permission": VIEW,
                    "scope": "related:venue",
                    "targets": f"{arena.pk}, {arena.pk}",
                    "reason": "cover",
                }
            ]
        ),
        instance=guest,
        prefix="user_grants",
    )
    assert formset.is_valid(), formset.errors
    formset.save()
    row = UserGrant.objects.get(user=guest)
    assert row.granted_by == root and row.targets == [str(arena.pk)] and row.reason == "cover"


def test_the_inline_refuses_bad_and_unheld_grants() -> None:
    organizer = _user("o@example.com", "organizer")
    guest = _user("guest@example.com")
    formset_class = _inline(guest, organizer)

    def errors(row: dict[str, Any]) -> str:
        formset = formset_class(data=_formset_data([row]), instance=guest, prefix="user_grants")
        assert not formset.is_valid()
        return str(formset.errors)

    assert "E363" not in errors({"permission": "testapp.event:aprove", "scope": "all"})
    assert "E360" in errors({"permission": "testapp.event:aprove", "scope": "all"})
    assert "E361" in errors({"permission": VIEW, "scope": "related:city"})
    assert "you do not hold testapp.event:approve" in errors(
        {"permission": APPROVE, "scope": "all"}
    )
    assert "only as own" in errors({"permission": VIEW, "scope": "all"})
    assert not UserGrant.objects.exists()


def test_the_inline_edits_and_expires(root: Any) -> None:
    organizer = _user("o@example.com", "organizer")
    guest = _user("guest@example.com")
    row = grants.grant(root, guest, VIEW, "all", reason="first")
    formset_class = _inline(guest, organizer)
    base = {"id": str(row.pk), "user": str(guest.pk), "permission": VIEW, "scope": "all"}
    # a new reason and Expire now give nothing more: the organizer may do it
    formset = formset_class(
        data=_formset_data([{**base, "reason": "ended", "expire_now": "on"}], initial=1),
        instance=guest,
        prefix="user_grants",
    )
    assert formset.is_valid(), formset.errors
    formset.save()
    row.refresh_from_db()
    assert row.reason == "ended" and not row.is_live and row.granted_by == root
    # widening needs what the operator holds
    formset = formset_class(
        data=_formset_data([{**base, "permission": APPROVE, "reason": "ended"}], initial=1),
        instance=guest,
        prefix="user_grants",
    )
    assert not formset.is_valid() and "E363" in str(formset.errors)


# the grants admin


def test_the_grants_admin_adds_lists_and_expires(root: Any) -> None:
    guest = _user("guest@example.com")
    client = _signed_in(root)
    response = client.post(
        f"{GRANTS}add/",
        {"user": str(guest.pk), "permission": VIEW, "scope": "all", "targets": "", "reason": "x"},
    )
    assert response.status_code == 302, response.content.decode()[:2000]
    row = UserGrant.objects.get(user=guest)
    assert row.granted_by == root and row.is_live
    listing = client.get(GRANTS, {"user": str(guest.pk)}).content.decode()
    assert "guest@example.com" in listing and "live" in listing
    expired = client.post(GRANTS, {"action": "expire_selected", "_selected_action": [str(row.pk)]})
    assert expired.status_code == 302
    row.refresh_from_db()
    assert not row.is_live
    assert "expired" in client.get(GRANTS, {"status": "expired"}).content.decode()
    history = client.get(f"{GRANTS}{row.pk}/history/")
    assert history.status_code == 200 and "expires_at" in history.content.decode()


def test_the_grants_admin_needs_the_usergrant_grants() -> None:
    staff = _user("staff@example.com", is_staff=True)
    client = _signed_in(staff)
    assert client.get(GRANTS).status_code == 403
    organizer = _user("o@example.com", "organizer", is_staff=True)
    assert _signed_in(organizer).get(GRANTS).status_code == 200


# effective permissions: role grants and user grants, marked by source


def test_effective_permissions_mark_each_source(root: Any) -> None:
    arena = Venue.objects.create(name="Arena", city="Pune")
    alice = _user("alice@example.com", "organizer")
    later = timezone.now() + timedelta(days=5)
    row = grants.grant(
        root,
        alice,
        VIEW,
        "related:venue",
        targets=[arena.pk],
        expires_at=later,
        reason="cover",
    )
    page = _signed_in(root).get(f"/admin/karni_accounts/user/{alice.pk}/permissions/")
    html = page.content.decode()
    assert page.status_code == 200
    assert "role organizer grants own" in html
    assert f"user grant {row.pk} grants related:venue" in html and "cover" in html
    assert f"{GRANTS}?user={alice.pk}" in html

    api = APIClient()
    api.force_authenticate(alice)
    body = api.get("/api/auth/permissions/effective/").json()
    entry = next(e for e in body["permissions"] if e["permission"] == VIEW)
    origins = [source["origin"] for source in entry["sources"]]
    assert origins == ["declared", "user_grant"]
    granted = entry["sources"][1]
    assert granted["grant"] == str(row.pk) and granted["targets"] == [str(arena.pk)]
    assert granted["reason"] == "cover" and granted["expires_at"] == later.isoformat()
    assert "grant" not in entry["sources"][0]
