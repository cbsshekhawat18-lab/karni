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
    assert set(isolation_dimensions()) == {"owner", "tenant"}
    report = assert_isolated(crud_urls.EventViewSet, "organizer")  # unchanged call
    assert report.dimensions == ["owner", "tenant"] and seen == ["theirs", "mine"]
    assert assert_isolated(crud_urls.EventViewSet, "organizer", by="owner").dimensions == ["owner"]
    with pytest.raises(AssertionError, match="Unknown isolation dimension"):
        assert_isolated(crud_urls.EventViewSet, by="region")
