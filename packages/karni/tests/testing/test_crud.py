"""karni.testing.api: client_as, APITestCase and assert_crud — passing and failing on purpose."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from karni.accounts.permissions import user_roles
from karni.testing import APITestCase, assert_crud, client_as, user_with_roles
from karni.testing.api import CHECKS, KarniAPIClient, expectation, resolve_resource
from tests.testapp.models import Event, Venue
from tests.testing import crud_urls

CRUD_ROUTES = override_settings(
    ROOT_URLCONF="tests.testing.crud_urls",
    KARNI_API_ROUTER="tests.testing.crud_urls.get_router",
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _crud_routes() -> Iterator[None]:
    with CRUD_ROUTES:
        yield


def _fails(resource: object, role: str | None, *expected: str, **options: object) -> str:
    with pytest.raises(AssertionError) as caught:
        assert_crud(resource, role, **options)  # type: ignore[arg-type]
    message = str(caught.value)
    for fragment in expected:
        assert fragment in message, message
    return message


# clients


def test_client_as_authenticates_a_user_holding_the_roles() -> None:
    client = client_as("organizer", "editor")
    assert isinstance(client, KarniAPIClient)
    assert user_roles(client.user) == ["editor", "organizer"]
    assert client.get("/api/venues/").status_code == 200
    assert client_as(None).get("/api/venues/").status_code == 401
    plain = client_as()
    assert user_roles(plain.user) == []
    bob = user_with_roles("staff", email="bob@example.com")
    assert client_as(user=bob).user == bob and user_roles(bob) == ["staff"]


@CRUD_ROUTES
class ClientAsTests(APITestCase):
    def test_same_roles_same_user_all_test_long(self) -> None:
        first = self.client_as("organizer")
        assert self.client_as("organizer").user == first.user
        assert self.client_as("staff").user != first.user
        assert self.user_as("organizer") == first.user
        assert self.client_as(None).user is None
        response = first.post("/api/events/", {"title": "Mine", "starts_at": "2030-01-01T10:00Z"})
        assert response.status_code == 201
        assert Event.objects.get(pk=response.json()["id"]).organizer == first.user

    def test_assert_crud_and_assert_isolated_as_methods(self) -> None:
        report = self.assert_crud(crud_urls.EventViewSet, "organizer")
        assert set(report.passed) == set(CHECKS)
        assert self.assert_isolated(crud_urls.EventViewSet, "organizer").dimensions == ["owner"]


# the full surface passes for well-behaved resources


def test_the_full_crud_surface_of_an_owned_resource() -> None:
    report = assert_crud(crud_urls.EventViewSet, "organizer")
    assert report.passed == list(CHECKS) and not report.failures


def test_a_read_only_role_gets_exactly_the_promised_denials() -> None:
    # Venues: everyone signed in reads, staff write. A viewer may list and
    # retrieve; create/update/delete must be 403 — and that is a pass.
    report = assert_crud(crud_urls.VenueViewSet, "viewer")
    assert not report.failures and "create" in report.passed and "delete" in report.passed
    assert not assert_crud(crud_urls.VenueViewSet, "staff").failures


def test_resources_resolve_by_model_route_and_label() -> None:
    assert resolve_resource(Venue).viewset is crud_urls.VenueViewSet  # first route for the model
    assert resolve_resource("public-venues").viewset is crud_urls.PublicVenueViewSet
    assert resolve_resource("/api/events/").viewset is crud_urls.EventViewSet
    assert resolve_resource("testapp.Event").viewset is crud_urls.EventViewSet
    assert_crud("public-venues")  # public reads: the anonymous list must be 200


def test_expectations_follow_the_declaration() -> None:
    resource = resolve_resource(crud_urls.EventViewSet)
    organizer, outsider = user_with_roles("organizer"), user_with_roles()
    own = Event.objects.create(title="x", starts_at="2030-01-01T10:00Z", organizer=organizer)
    assert expectation(resource, "create", organizer).allowed
    denied = expectation(resource, "create", outsider)
    assert denied.statuses == {403} and "HasRole('organizer')" in denied.describe()
    assert expectation(resource, "retrieve", outsider, own).statuses == {404}
    assert expectation(resource, "destroy", None, own).statuses == {401, 403}


def test_values_payload_expect_and_skip() -> None:
    report = assert_crud(
        crud_urls.EventViewSet,
        "organizer",
        values={"capacity": 40},
        payload={"description": "From the test"},
        skip=("filtering", "pagination"),
    )
    assert "filtering" in report.skipped and "pagination" in report.skipped
    assert Event.objects.filter(description="From the test").exists()
    _fails(
        crud_urls.EventViewSet,
        "organizer",
        "delete: DELETE",
        "answered 204, expected 403 (pinned by expect=)",
        expect={"destroy": 403},
    )
    with pytest.raises(ValueError, match="unknown checks"):
        assert_crud(crud_urls.EventViewSet, "organizer", skip=("nope",))


# and fails, naming what broke


def test_a_missing_permission_check_fails_the_denials() -> None:
    message = _fails(
        crud_urls.NoGateEventViewSet,
        "organizer",
        "denials: POST /api/no-gate-events/ as anonymous answered 201, expected 401/403",
        "access create=HasRole('organizer')",
        "as a user without the role answered 201, expected 403",
        "changed the row count",
    )
    assert "NoGateEventViewSet" in message


def test_broken_pagination_fails_naming_the_paginator() -> None:
    _fails(
        crud_urls.BrokenPaginationEventViewSet,
        "organizer",
        "pagination: GET /api/broken-pagination-events/?page_size=2 returned",
        "the paginator ignores page_size (IgnoresPageSize)",
    )


def test_ignored_filters_fail() -> None:
    _fails(
        crud_urls.BrokenFilteringEventViewSet,
        "organizer",
        "filtering: GET /api/broken-filtering-events/?title=",
        "the filter is ignored",
    )


def test_an_undocumented_response_field_breaks_the_contract() -> None:
    _fails(
        crud_urls.UndocumentedFieldVenueViewSet,
        "staff",
        "schema: GET /api/undocumented-venues/",
        "undocumented: not declared in the schema",
    )


def test_an_owner_that_is_not_stamped_fails_create() -> None:
    _fails(
        crud_urls.NoStampEventViewSet,
        "organizer",
        "create: Event.organizer was not stamped with the requester",
    )


def test_a_viewset_without_access_fails_naming_the_fix() -> None:
    _fails(
        crud_urls.UndeclaredEventViewSet,
        "organizer",
        "access: E101: UndeclaredEventViewSet declares no",
    )


def test_a_role_refused_everything_is_reported() -> None:
    _fails(crud_urls.StaffVenueViewSet, "stafff", "role 'stafff' is refused every action")
    assert_crud(crud_urls.StaffVenueViewSet, "viewer", expect={"list": 403, "create": 403})
    assert not assert_crud(crud_urls.StaffVenueViewSet, "staff").failures


def test_an_unrouted_viewset_is_reported() -> None:
    from karni.api import Access, Authenticated, BaseViewSet

    class Unrouted(BaseViewSet):
        model = Venue
        access = Access(read=Authenticated(), write=Authenticated())

    with pytest.raises(AssertionError, match="is not routed"):
        assert_crud(Unrouted)
    with pytest.raises(AssertionError, match="No route 'nowhere'"):
        assert_crud("nowhere")
    with pytest.raises(AssertionError, match="No routed viewset serves"):
        assert_crud(get_user_model())


def test_the_client_as_fixture(client_as: Any) -> None:
    organizer = client_as("organizer")
    assert client_as("organizer").user == organizer.user
    assert client_as(None).user is None
    assert organizer.get("/api/events/").status_code == 200


def test_generated_values_are_reseeded_per_test() -> None:
    from karni.testing.factories import build

    first = build(Event).title
    from factory.random import reseed_random

    reseed_random("0:tests/testing/test_crud.py::test_generated_values_are_reseeded_per_test")
    assert build(Event).title == first
