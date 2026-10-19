"""karni.testing.isolation: the one-line "another owner's rows are out of reach" test."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from karni.testing import assert_isolated
from karni.testing import isolation as isolation_mod
from karni.testing.isolation import (
    Isolation,
    IsolationCase,
    Principal,
    isolation_dimensions,
    register_isolation,
)
from tests.testapp.models import Event
from tests.testing import crud_urls
from tests.testing.test_crud import CRUD_ROUTES

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _crud_routes() -> Iterator[None]:
    with CRUD_ROUTES:
        yield


def test_owners_cannot_reach_each_others_rows() -> None:
    report = assert_isolated(crud_urls.EventViewSet, "organizer")
    assert report.dimensions == ["owner"] and not report.failures
    assert_isolated(crud_urls.EventViewSet, "organizer", owner="organizer", by="owner")


def test_a_bypass_role_is_not_isolated() -> None:
    with pytest.raises(AssertionError) as caught:
        assert_isolated(crud_urls.EventViewSet, "staff")  # read=Owned(...) | HasRole("staff")
    assert "owner: GET /api/events/ as mine lists another owner's row" in str(caught.value)
    assert "answered 200, expected 404" in str(caught.value)


def test_a_viewset_that_bypasses_its_read_scope_leaks() -> None:
    with pytest.raises(AssertionError) as caught:
        assert_isolated(crud_urls.LeakyEventViewSet, "organizer")
    message = str(caught.value)
    assert "for role 'organizer': rows leak" in message
    assert "GET /api/leaky-events/ as mine lists another owner's row" in message
    assert "(another owner's row) as mine answered 200, expected 404" in message


def test_a_body_that_chooses_the_owner_is_caught() -> None:
    with pytest.raises(AssertionError, match="the body chose the owner"):
        assert_isolated(crud_urls.OwnerFromBodyEventViewSet, "organizer")


def test_unscoped_reads_name_the_missing_owner() -> None:
    with pytest.raises(AssertionError) as caught:
        assert_isolated(crud_urls.VenueViewSet)
    message = str(caught.value)
    assert "nothing isolates rows" in message and "read=Authenticated() names no Owned" in message


def test_new_dimensions_join_without_changing_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    class FakeTenant(Isolation):
        name = "tenant"

        def applies(self, case: IsolationCase) -> bool:
            return True

        def row(self, case: IsolationCase, principal: Principal) -> Event:
            seen.append(principal.label)
            return isolation_mod.OwnerIsolation().row(case, principal)

    monkeypatch.setattr(isolation_mod, "_REGISTERED", dict(isolation_mod._REGISTERED))
    register_isolation(FakeTenant())
    assert set(isolation_dimensions()) == {"owner", "grant", "tenant"}
    report = assert_isolated(crud_urls.EventViewSet, "organizer")  # unchanged call
    assert report.dimensions == ["owner", "tenant"] and seen == ["theirs", "mine"]
    assert assert_isolated(crud_urls.EventViewSet, "organizer", by="owner").dimensions == ["owner"]
    with pytest.raises(AssertionError, match="Unknown isolation dimension"):
        assert_isolated(crud_urls.EventViewSet, by="region")


# the grant dimension (ADR 0002, P2)

GRANT_ROLES = {
    "staff": {"system": True, "grants": {"*": "all"}},
    "organizer": {"grants": {"testapp.event:*": "own", "testapp.venue:view": "all"}},
    "venue_manager": {
        "grants": {
            "testapp.event:view": "related:venue",
            "testapp.event:change": "related:venue",
            "testapp.venue:view": "all",
        }
    },
    "reader": {"grants": {"testapp.event:view": "all"}},
}


@pytest.fixture
def grants() -> Iterator[None]:
    from django.test import override_settings

    from karni.accounts.roles import sync_roles

    with override_settings(KARNI_ROLES=GRANT_ROLES):
        sync_roles()
        yield


def test_an_own_grant_partitions_rows_on_every_surface(grants: None) -> None:
    report = assert_isolated(crud_urls.GrantedEventViewSet, "organizer")
    assert report.dimensions == ["grant"]
    # Event is in the admin: the admin probe ran, the owner-field one too.
    assert not any(note.startswith("grant: admin") for note in report.notes)


def test_a_related_grant_partitions_rows(grants: None) -> None:
    report = assert_isolated(crud_urls.GrantedEventViewSet, "venue_manager")
    assert report.dimensions == ["grant"]
    # The test user model has no `venue` field: the scope lives on the
    # instance, so the admin (which reloads the user) is skipped and says so.
    assert any("admin: the scope lives on the user instance" in note for note in report.notes)


def test_an_all_grant_is_not_isolated_and_says_why(grants: None) -> None:
    with pytest.raises(AssertionError, match="holds no 'own' or 'related:<key>' grant"):
        assert_isolated(crud_urls.GrantedEventViewSet, "reader")


def test_the_admin_probe_catches_an_exempt_admin(
    grants: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from django.contrib import admin

    # The admin URLs are bound to the registered admin instance, so the
    # exemption is switched on that admin's (per-model) class.
    registered = type(admin.site._registry[Event])
    monkeypatch.setattr(registered, "scope_exempt", True)
    monkeypatch.setattr(registered, "scope_exempt_reason", "the support console sees every event")
    with pytest.raises(AssertionError, match="E606") as excinfo:
        assert_isolated(crud_urls.GrantedEventViewSet, "organizer")
    message = str(excinfo.value)
    assert "grant: admin:" in message and "lists another grant's row" in message
    assert "GET /api/granted-events/" not in message  # the API itself held
