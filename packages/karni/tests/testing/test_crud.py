"""karni.testing.api: client_as, APITestCase and assert_crud — passing and failing on purpose."""

from __future__ import annotations

import sys
import warnings
from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from karni.accounts.permissions import user_roles
from karni.testing import APITestCase, assert_crud, client_as, user_with_roles
from karni.testing.api import (
    CHECKS,
    KarniAPIClient,
    build_payload,
    expectation,
    image_upload,
    png_bytes,
    resolve_resource,
)
from tests.testapp.models import Event, Venue
from tests.testing import crud_urls
from tests.uploadsapp.models import Attachment, Photo

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
    # retrieve, and create/update/delete must be 403. That is a pass, with a
    # warning that no write was exercised.
    with pytest.warns(UserWarning, match="no write exercised"):
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
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # pinned refusals are intended: no warning
        report = assert_crud(
            crud_urls.StaffVenueViewSet, "viewer", expect={"list": 403, "create": 403}
        )
    assert not report.warnings
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


def test_visibility_passes_for_the_generated_serializer() -> None:
    """Customer hides note and salary from ``user`` and protects phone (P3)."""
    report = assert_crud(crud_urls.CustomerViewSet, "user")
    assert "visibility" in report.passed


def test_visibility_catches_a_serializer_that_ignores_field_roles() -> None:
    message = _fails(
        crud_urls.LeakyCustomerViewSet,
        "user",
        "visibility: GET /api/leaky-customers/ returns internal_note, salary",
        "field_roles hides from role 'user'",
    )
    assert "PATCH phone as role 'user' answered 200" in message


def test_visibility_is_skipped_without_field_roles() -> None:
    report = assert_crud(crud_urls.VenueViewSet, "staff")
    assert any(entry.startswith("visibility") for entry in report.skipped)


def test_generated_values_are_reseeded_per_test() -> None:
    from karni.testing.factories import build

    first = build(Event).title
    from factory.random import reseed_random

    reseed_random("0:tests/testing/test_crud.py::test_generated_values_are_reseeded_per_test")
    assert build(Event).title == first


# uploads: a required ImageField needs a real image, a FileField any file


@pytest.mark.parametrize(
    ("viewset", "model", "name"),
    [
        (crud_urls.PhotoViewSet, Photo, "image"),
        (crud_urls.AttachmentViewSet, Attachment, "file"),
    ],
)
def test_required_uploads_pass_with_no_payload_and_store_files(
    viewset: type[Any], model: type[Any], name: str
) -> None:
    report = assert_crud(viewset, "staff", payload={"title": "sent by the test"})
    assert not report.failures
    assert {"create", "update", "delete", "denials", "pagination"} <= set(report.passed)
    # The POST created one row and the PUT renamed another: both hold the upload.
    rows = list(model.objects.filter(title="sent by the test"))
    assert len(rows) == 2
    for row in rows:
        stored = getattr(row, name)
        assert stored.name and stored.size > 0, (row, stored.name)
    if name == "image":
        assert all(getattr(row, name).size == len(png_bytes()) for row in rows)


def test_the_create_body_sends_a_png_for_an_image_and_text_for_a_file() -> None:
    staff = user_with_roles("staff")
    photo = build_payload(resolve_resource(crud_urls.PhotoViewSet), staff)
    assert photo.multipart and photo.files == ["image"] and photo.format == "multipart"
    assert photo.data["image"].name == "image.png"
    assert photo.data["image"].content_type == "image/png"
    assert photo.data["image"].read() == png_bytes()
    attachment = build_payload(resolve_resource(crud_urls.AttachmentViewSet), staff)
    assert attachment.files == ["file"] and attachment.data["file"].name == "file.txt"
    # Every build makes new uploads: nothing is shared between requests.
    again = build_payload(resolve_resource(crud_urls.PhotoViewSet), staff)
    assert again.data["image"] is not photo.data["image"]


def test_one_upload_passed_as_payload_serves_every_request() -> None:
    shared = SimpleUploadedFile("mine.png", png_bytes(), content_type="image/png")
    report = assert_crud(
        crud_urls.PhotoViewSet, "staff", payload={"image": shared, "title": "shared"}
    )
    assert not report.failures
    rows = list(Photo.objects.filter(title="shared"))
    assert len(rows) == 2 and all(row.image.size == len(png_bytes()) for row in rows)


def test_isolation_posts_a_body_with_an_image_as_multipart() -> None:
    from karni.testing import assert_isolated

    assert_crud(crud_urls.OwnedPhotoViewSet)
    assert assert_isolated(crud_urls.OwnedPhotoViewSet).dimensions == ["owner"]


def test_an_image_upload_without_pillow_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    png_bytes.cache_clear()
    monkeypatch.setitem(sys.modules, "PIL", None)
    try:
        with pytest.raises(AssertionError, match=r"pip install 'karni\[images\]'") as caught:
            image_upload("image")
        assert "E501" in str(caught.value)
    finally:
        png_bytes.cache_clear()


# writes that are never exercised are visible


def test_a_role_that_may_not_write_is_warned_about_and_listed() -> None:
    with pytest.warns(UserWarning, match="refuses writes to role 'viewer'") as caught:
        report = assert_crud(crud_urls.PhotoViewSet, "viewer")
    assert not report.failures
    entry = next(e for e in report.skipped if e.startswith("no write exercised"))
    assert "Pass a role that may write" in entry and "HasRole('staff')" in entry
    assert report.warnings == [f"assert_crud(PhotoViewSet) {entry}"]
    assert str(caught[0].message).startswith("assert_crud(PhotoViewSet) no write exercised")
    with pytest.warns(UserWarning, match="refuses writes to any signed-in user"):
        assert_crud(crud_urls.AttachmentViewSet)
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # a writing role exercises the writes: no warning
        assert not assert_crud(crud_urls.PhotoViewSet, "staff").warnings


# rows the read rule hides are named, not blamed on the paginator


def test_rows_hidden_by_the_read_rule_are_reported_with_the_fix() -> None:
    message = _fails(
        crud_urls.PublishedEventViewSet,
        "organizer",
        "list: GET /api/published-events/ does not include the requester's row",
        "pagination: GET /api/published-events/?page_size=2 returned 0 rows, but none of the "
        "3 rows assert_crud just created for the requester is listed",
        "the read rule hides them from this user (access=Access(read=Where(published)",
        "Run karni why-empty published-events --as <a user with role 'organizer'> to see "
        "which step drops them.",
    )
    assert "the paginator ignores" not in message


def test_rows_the_declaration_allows_but_the_queryset_drops_are_named() -> None:
    message = _fails(
        crud_urls.EmptyEventViewSet,
        "organizer",
        "pagination: GET /api/empty-events/?page_size=2 returned 0 rows, but none of the 3 rows",
        "lets this user read them, so the viewset's queryset (get_queryset, read_scope) or its "
        "paginator leaves them out",
        "karni why-empty empty-events --as <a user with role 'organizer'>",
    )
    assert "the paginator ignores" not in message and "paginator is not at fault" not in message


def test_an_explicit_user_with_roles_is_named_by_its_roles() -> None:
    viewer = user_with_roles("viewer")
    with pytest.warns(UserWarning, match=r"refuses writes to the requester \(roles viewer\)"):
        assert_crud(crud_urls.PhotoViewSet, user=viewer)


def test_a_payload_value_that_replaces_an_upload_is_not_checked_as_a_file() -> None:
    staff = user_with_roles("staff")
    body = build_payload(resolve_resource(crud_urls.PhotoViewSet), staff, payload={"image": ""})
    assert body.files == [] and not body.multipart
