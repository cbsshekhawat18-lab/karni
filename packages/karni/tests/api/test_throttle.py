"""Per-action rate limits: ``throttle = Throttle(create="2/hour")`` (karni.api.throttling).

Throttle history lives in ``caches["default"]`` (locmem here), so every test
clears it. Rates from settings are patched on ``SimpleRateThrottle.THROTTLE_RATES``,
the dict DRF binds once from ``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]``
(see ``tests/accounts/test_ratelimit.py``).
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache
from django.test import override_settings
from drf_spectacular.generators import SchemaGenerator
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle, UserRateThrottle

from karni.api import Access, Authenticated, BaseViewSet, Public, Throttle
from karni.api.routers import KarniRouter
from karni.api.throttling import ActionRateThrottle, throttle_rate, throttle_scope
from karni.exceptions import KarniImproperlyConfigured
from karni.testing.api import _unthrottled
from tests.testapp.models import Venue

pytestmark = pytest.mark.django_db

ROUTER = "tests.api.test_throttle"


class ContactViewSet(BaseViewSet):
    """A public form: anyone may create, two per hour and caller."""

    model = Venue
    access = Access(read=Public(), write=Authenticated(), create=Public())
    throttle = Throttle(create="2/hour")

    @action(detail=False, methods=["post"], access=Public())
    def subscribe(self, request: Request) -> Response:
        return Response({"ok": True})


def contacts_router() -> KarniRouter:
    router = KarniRouter()
    router.register("contacts", ContactViewSet, basename="contacts")
    router.autodiscover()
    return router


@pytest.fixture(autouse=True)
def _clean_throttle_cache() -> Any:
    cache.clear()
    yield
    cache.clear()


def _post(action_name: str = "create", *, ip: str = "10.0.0.1") -> Any:
    request = APIRequestFactory().post(
        "/", {"name": "Ada", "city": "Berlin"}, format="json", REMOTE_ADDR=ip
    )
    return ContactViewSet.as_view({"post": action_name})(request)


def _list(*, ip: str = "10.0.0.1") -> Any:
    request = APIRequestFactory().get("/", REMOTE_ADDR=ip)
    return ContactViewSet.as_view({"get": "list"})(request)


def test_declaration_adds_the_throttle_class_to_the_viewset() -> None:
    assert ContactViewSet.throttle_classes == [
        AnonRateThrottle,
        UserRateThrottle,
        ActionRateThrottle,
    ]
    assert ActionRateThrottle not in BaseViewSet.throttle_classes
    assert repr(ContactViewSet.throttle) == "Throttle(create='2/hour')"


def test_over_the_rate_answers_429_with_retry_after() -> None:
    assert _post().status_code == 201
    assert _post().status_code == 201
    third = _post()
    assert third.status_code == 429
    assert "Retry-After" in third
    assert Venue.objects.count() == 2


def test_actions_the_declaration_does_not_name_are_not_limited() -> None:
    for _ in range(3):
        _post()
    assert _post().status_code == 429
    for _ in range(5):
        assert _list().status_code == 200
        assert _post("subscribe").status_code == 200


def test_callers_are_counted_apart() -> None:
    assert _post(ip="10.0.0.1").status_code == 201
    assert _post(ip="10.0.0.1").status_code == 201
    assert _post(ip="10.0.0.1").status_code == 429
    assert _post(ip="10.0.0.2").status_code == 201


def test_scope_is_the_route_prefix_and_the_action() -> None:
    assert throttle_scope(ContactViewSet, "create") == "ContactViewSet.create"
    with override_settings(KARNI_API_ROUTER=f"{ROUTER}.contacts_router"):
        assert throttle_scope(ContactViewSet, "create") == "contacts.create"
        assert throttle_rate(ContactViewSet, "create") == "2/hour"
        assert throttle_rate(ContactViewSet, "list") is None


def test_a_rate_in_settings_replaces_the_declared_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "ContactViewSet.create", "1/hour")
    assert throttle_rate(ContactViewSet, "create") == "1/hour"
    assert _post().status_code == 201
    assert _post().status_code == 429


def test_none_in_settings_switches_the_limit_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "ContactViewSet.create", None)
    assert throttle_rate(ContactViewSet, "create") is None
    for _ in range(4):
        assert _post().status_code == 201


def test_turning_throttle_classes_off_covers_the_declaration() -> None:
    """``assert_crud`` and ``karni why`` turn throttling off through ``throttle_classes``."""
    with _unthrottled(ContactViewSet):
        for _ in range(4):
            assert _post().status_code == 201
    assert ActionRateThrottle in ContactViewSet.throttle_classes


def test_schema_publishes_the_rate_in_force(monkeypatch: pytest.MonkeyPatch) -> None:
    def paths() -> dict[str, Any]:
        schema = SchemaGenerator(patterns=contacts_router().urls).get_schema(
            request=None, public=True
        )
        return dict(schema["paths"])

    assert paths()["/contacts/"]["post"]["x-karni-throttle"] == "2/hour"
    assert "x-karni-throttle" not in paths()["/contacts/"]["get"]
    assert "x-karni-throttle" not in paths()["/contacts/subscribe/"]["post"]
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "ContactViewSet.create", "5/day")
    assert paths()["/contacts/"]["post"]["x-karni-throttle"] == "5/day"


def test_invalid_declarations_fail_at_class_definition() -> None:
    with pytest.raises(KarniImproperlyConfigured, match="E132.*names no action"):
        Throttle()
    with pytest.raises(KarniImproperlyConfigured, match="E132.*is not a rate"):
        Throttle(create="ten per hour")
    with pytest.raises(KarniImproperlyConfigured, match="E132.*unknown action.*fly"):

        class Flying(BaseViewSet):
            model = Venue
            access = Access(read=Public(), write=Authenticated())
            throttle = Throttle(fly="1/min")

    with pytest.raises(KarniImproperlyConfigured, match="E132.*must be a Throttle"):

        class Stringly(BaseViewSet):
            model = Venue
            access = Access(read=Public(), write=Authenticated())
            throttle = "1/min"  # type: ignore[assignment]
