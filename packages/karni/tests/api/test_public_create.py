"""Public creates are safe by default: a rate limit, a honeypot, and no anonymous imports.

A viewset whose ``create`` lets anonymous callers in gets
``KARNI_PUBLIC_CREATE_RATE`` (default ``"10/hour"``) on ``create`` without a
``throttle`` declaration, and a honeypot field
(``KARNI_PUBLIC_CREATE_HONEYPOT_FIELD``, default ``"homepage"``). The pytest
plugin gives every test an empty throttle cache, so no test here clears one.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from drf_spectacular.generators import SchemaGenerator
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle

from karni.api import Access, BaseViewSet, HasRole, Public, Throttle, Where
from karni.api.access import Authenticated, admits_anyone
from karni.api.routers import KarniRouter
from karni.api.throttling import (
    DEFAULT_PUBLIC_CREATE_RATE,
    ActionRateThrottle,
    is_public_create,
    throttle_rate,
)
from tests.testapp.models import Venue

pytestmark = pytest.mark.django_db

STAFF = HasRole("staff")


class EnquiryViewSet(BaseViewSet):
    """A contact form: anyone sends one, only staff read them."""

    model = Venue
    access = Access(read=STAFF, write=STAFF, create=Public())


class TightViewSet(BaseViewSet):
    model = Venue
    access = Access(read=STAFF, write=STAFF, create=Public())
    throttle = Throttle(create="1/hour")


class UnlimitedViewSet(BaseViewSet):
    model = Venue
    access = Access(read=STAFF, write=STAFF, create=Public())
    throttle = Throttle(create=None)


class StaffOnlyViewSet(BaseViewSet):
    model = Venue
    access = Access(read=STAFF, write=STAFF)


class OwnThrottlesViewSet(BaseViewSet):
    """Sets throttle_classes itself: it owns its throttling, as in plain DRF."""

    model = Venue
    access = Access(read=STAFF, write=STAFF, create=Public())
    throttle_classes = [AnonRateThrottle]


def enquiries_router() -> KarniRouter:
    router = KarniRouter()
    router.register("enquiries", EnquiryViewSet, basename="enquiries")
    router.register("staff-venues", StaffOnlyViewSet, basename="staff-venues")
    return router


def _post(
    viewset: type[BaseViewSet],
    data: dict[str, Any] | None = None,
    *,
    user: Any = None,
    **extra: Any,
) -> Any:
    body = {"name": "Ada", "city": "Berlin"} if data is None else data
    request = APIRequestFactory().post("/", body, format="json", **extra)
    if user is not None:
        force_authenticate(request, user=user)
    return viewset.as_view({"post": "create"})(request)


def _staff() -> Any:
    user = get_user_model().objects.create_user(email="staff@example.com", password="x-long-pass")
    user.groups.add(Group.objects.get_or_create(name="staff")[0])
    return user


# --- which creates are public -------------------------------------------------


@pytest.mark.parametrize(
    ("predicate", "public"),
    [
        (Public(), True),
        (Public() | STAFF, True),
        (Public() & Public(), True),
        (Authenticated(), False),
        (STAFF, False),
        (Where(lambda request: True), False),
        (Public() & STAFF, False),
    ],
)
def test_admits_anyone(predicate: Any, public: bool) -> None:
    assert admits_anyone(predicate) is public


def test_a_public_write_makes_create_public_too() -> None:
    class OpenViewSet(BaseViewSet):
        model = Venue
        access = Access(read=Public(), write=Public())

    assert is_public_create(OpenViewSet) is True
    assert is_public_create(StaffOnlyViewSet) is False
    assert is_public_create(EnquiryViewSet) is True


# --- the default rate ---------------------------------------------------------


def test_every_viewset_carries_the_action_throttle() -> None:
    assert ActionRateThrottle in EnquiryViewSet.throttle_classes
    assert ActionRateThrottle in StaffOnlyViewSet.throttle_classes
    assert OwnThrottlesViewSet.throttle_classes == [AnonRateThrottle]


def test_a_public_create_is_limited_by_default() -> None:
    assert DEFAULT_PUBLIC_CREATE_RATE == "10/hour"
    assert throttle_rate(EnquiryViewSet, "create") == "10/hour"
    for _ in range(10):
        assert _post(EnquiryViewSet).status_code == 201
    eleventh = _post(EnquiryViewSet)
    assert eleventh.status_code == 429
    assert "Retry-After" in eleventh
    assert Venue.objects.count() == 10


def test_anonymous_callers_are_counted_per_ip() -> None:
    with override_settings(KARNI_PUBLIC_CREATE_RATE="1/hour"):
        assert _post(EnquiryViewSet, REMOTE_ADDR="10.0.0.1").status_code == 201
        assert _post(EnquiryViewSet, REMOTE_ADDR="10.0.0.1").status_code == 429
        assert _post(EnquiryViewSet, REMOTE_ADDR="10.0.0.2").status_code == 201


def test_the_setting_changes_the_default() -> None:
    with override_settings(KARNI_PUBLIC_CREATE_RATE="2/hour"):
        assert throttle_rate(EnquiryViewSet, "create") == "2/hour"
        assert _post(EnquiryViewSet).status_code == 201
        assert _post(EnquiryViewSet).status_code == 201
        assert _post(EnquiryViewSet).status_code == 429


@pytest.mark.parametrize("off", [None, ""])
def test_none_in_the_setting_turns_the_default_off(off: str | None) -> None:
    with override_settings(KARNI_PUBLIC_CREATE_RATE=off):
        assert throttle_rate(EnquiryViewSet, "create") is None
        for _ in range(12):
            assert _post(EnquiryViewSet).status_code == 201


def test_the_viewset_declaration_overrides_the_default() -> None:
    assert throttle_rate(TightViewSet, "create") == "1/hour"
    assert _post(TightViewSet).status_code == 201
    assert _post(TightViewSet).status_code == 429


def test_none_in_the_declaration_turns_the_default_off() -> None:
    assert repr(UnlimitedViewSet.throttle) == "Throttle(create=None)"
    assert throttle_rate(UnlimitedViewSet, "create") is None
    for _ in range(12):
        assert _post(UnlimitedViewSet).status_code == 201


def test_the_per_scope_setting_still_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "EnquiryViewSet.create", "1/hour")
    assert throttle_rate(EnquiryViewSet, "create") == "1/hour"
    assert _post(EnquiryViewSet).status_code == 201
    assert _post(EnquiryViewSet).status_code == 429
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "UnlimitedViewSet.create", "1/hour")
    assert throttle_rate(UnlimitedViewSet, "create") == "1/hour"
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "TightViewSet.create", None)
    assert throttle_rate(TightViewSet, "create") is None


def test_a_create_that_needs_a_role_is_not_limited_by_default() -> None:
    staff = _staff()
    assert throttle_rate(StaffOnlyViewSet, "create") is None
    for index in range(12):
        response = _post(StaffOnlyViewSet, {"name": f"V{index}", "city": "Paris"}, user=staff)
        assert response.status_code == 201


def test_a_viewset_with_its_own_throttle_classes_gets_no_default() -> None:
    for _ in range(12):
        assert _post(OwnThrottlesViewSet).status_code == 201


def test_other_actions_of_a_public_create_viewset_are_not_limited() -> None:
    assert throttle_rate(EnquiryViewSet, "list") is None
    assert throttle_rate(EnquiryViewSet, "update") is None


# --- the schema ---------------------------------------------------------------


def _paths() -> dict[str, Any]:
    schema = SchemaGenerator(patterns=enquiries_router().urls).get_schema(request=None, public=True)
    return dict(schema["paths"])


def test_the_schema_publishes_the_rate_and_the_honeypot() -> None:
    paths = _paths()
    create = paths["/enquiries/"]["post"]
    assert create["x-karni-throttle"] == "10/hour"
    assert create["x-karni-honeypot"] == "homepage"
    assert "x-karni-throttle" not in paths["/enquiries/"]["get"]
    assert "x-karni-honeypot" not in paths["/staff-venues/"]["post"]
    assert "x-karni-throttle" not in paths["/staff-venues/"]["post"]


def test_the_honeypot_is_not_a_field_of_the_request_body() -> None:
    schema = SchemaGenerator(patterns=enquiries_router().urls).get_schema(request=None, public=True)
    for component in schema["components"]["schemas"].values():
        assert "homepage" not in component.get("properties", {})
        assert "homepage" not in component.get("required", [])


# --- the honeypot -------------------------------------------------------------


def test_a_filled_honeypot_is_accepted_and_nothing_is_saved() -> None:
    from structlog.testing import capture_logs

    with capture_logs() as logs:
        response = _post(EnquiryViewSet, {"name": "Bot", "city": "X", "homepage": "http://spam"})
    assert response.status_code == 202
    assert response.data == {"detail": "Received."}
    assert not Venue.objects.exists()
    events = [entry for entry in logs if entry["event"] == "karni.api.honeypot"]
    assert events and events[0]["viewset"] == "EnquiryViewSet"


@pytest.mark.parametrize("value", ["", "   ", None])
def test_an_empty_honeypot_saves_the_row(value: str | None) -> None:
    response = _post(EnquiryViewSet, {"name": "Ada", "city": "Berlin", "homepage": value})
    assert response.status_code == 201
    assert Venue.objects.count() == 1


def test_an_empty_setting_turns_the_honeypot_off() -> None:
    with override_settings(KARNI_PUBLIC_CREATE_HONEYPOT_FIELD=""):
        response = _post(EnquiryViewSet, {"name": "Ada", "city": "Berlin", "homepage": "x"})
    assert response.status_code == 201
    assert Venue.objects.count() == 1


def test_a_model_field_of_that_name_is_never_swallowed() -> None:
    with override_settings(KARNI_PUBLIC_CREATE_HONEYPOT_FIELD="city"):
        assert EnquiryViewSet().get_honeypot_field() is None
        response = _post(EnquiryViewSet, {"name": "Ada", "city": "Berlin"})
    assert response.status_code == 201
    assert Venue.objects.get().city == "Berlin"


def test_a_create_that_needs_a_role_has_no_honeypot() -> None:
    assert StaffOnlyViewSet().get_honeypot_field() is None
    staff = _staff()
    response = _post(StaffOnlyViewSet, {"name": "V", "city": "P", "homepage": "x"}, user=staff)
    assert response.status_code == 201


def test_a_viewset_can_turn_its_honeypot_off() -> None:
    class NoTrapViewSet(EnquiryViewSet):
        def get_honeypot_field(self) -> str | None:
            return None

    response = _post(NoTrapViewSet, {"name": "Ada", "city": "Berlin", "homepage": "x"})
    assert response.status_code == 201


# --- imports ------------------------------------------------------------------


def test_a_public_create_does_not_open_imports_to_anonymous_callers() -> None:
    from django.core.files.uploadedfile import SimpleUploadedFile

    upload = SimpleUploadedFile("venues.csv", b"name,city\nA,B\n", content_type="text/csv")
    request = APIRequestFactory().post("/", {"file": upload}, format="multipart")
    response: Response = EnquiryViewSet.as_view({"post": "import_data"})(request)
    assert response.status_code in (401, 403)


def test_staff_may_still_import_into_a_public_create_resource() -> None:
    from django.core.files.uploadedfile import SimpleUploadedFile

    upload = SimpleUploadedFile("venues.csv", b"name,city\nA,B\n", content_type="text/csv")
    request = APIRequestFactory().post("/", {"file": upload}, format="multipart")
    force_authenticate(request, user=_staff())
    response: Response = EnquiryViewSet.as_view({"post": "import_data"})(request)
    assert response.status_code == 201, response.data
