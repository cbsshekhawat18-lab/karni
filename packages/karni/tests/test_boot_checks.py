"""System checks that surface declaration problems on boot (E101, E128, W101, E4xx)."""

from __future__ import annotations

from typing import Any

import pytest
from django.test import override_settings
from rest_framework import serializers

from karni.api.access import Access, Authenticated
from karni.api.routers import KarniRouter
from karni.api.viewsets import BaseViewSet
from karni.checks import check_schedules, check_throttle_cache, check_viewsets
from karni.errorcodes import docs_url
from karni.schedule import ScheduleError
from tests.testapp.models import Venue

pytestmark = pytest.mark.django_db


class PlainVenueSerializer(serializers.ModelSerializer):
    class Meta:
        model = Venue
        fields = "__all__"


class CustomVenueSerializer(serializers.ModelSerializer):
    shout = serializers.SerializerMethodField()

    class Meta:
        model = Venue
        fields = "__all__"

    def get_shout(self, obj: Venue) -> str:
        return obj.name.upper()


class DuplicatingVenueViewSet(BaseViewSet):
    model = Venue
    access = Access(read=Authenticated(), write=Authenticated())
    serializer_class = PlainVenueSerializer


class CustomVenueViewSet(BaseViewSet):
    model = Venue
    access = Access(read=Authenticated(), write=Authenticated())
    serializer_class = CustomVenueSerializer


def serializer_router() -> Any:
    router = KarniRouter()
    router.register("dup-venues", DuplicatingVenueViewSet, basename="dup-venues")
    router.register("custom-venues", CustomVenueViewSet, basename="custom-venues")
    return router


def _ids(messages: list[Any]) -> list[str]:
    return [message.id for message in messages]


_LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
_REDIS = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": "x"}}


def test_a_per_process_throttle_cache_warns_only_with_debug_off() -> None:
    """karni.W501: locmem counters are per worker; fine in DEBUG, a warning in production."""
    with override_settings(DEBUG=False, CACHES=_LOCMEM):
        (message,) = check_throttle_cache()
        assert message.id == "karni.W501" and "per worker" in message.msg
        assert docs_url("W501") in message.hint
    with override_settings(DEBUG=True, CACHES=_LOCMEM):
        assert check_throttle_cache() == []
    with override_settings(DEBUG=False, CACHES=_REDIS):
        assert check_throttle_cache() == []


def test_the_project_router_is_clean() -> None:
    assert check_viewsets() == []


@override_settings(KARNI_API_ROUTER="tests.testing.crud_urls.get_router")
def test_a_routed_viewset_without_access_fails_boot() -> None:
    messages = [m for m in check_viewsets() if m.id == "karni.E101"]
    assert messages, "UndeclaredEventViewSet is routed without access"
    (message,) = [m for m in messages if m.obj.__name__ == "UndeclaredEventViewSet"]
    assert "declares no `access`" in message.msg
    assert message.hint.endswith(f"See {docs_url('E101')}")
    assert "Unscoped(reason=" in message.hint


@override_settings(KARNI_API_ROUTER="nowhere.get_router")
def test_an_unimportable_router_factory_is_reported() -> None:
    assert _ids(check_viewsets()) == ["karni.E128"]


@override_settings(KARNI_API_ROUTER="tests.test_boot_checks.serializer_router")
def test_a_serializer_that_adds_nothing_is_flagged_and_a_custom_one_is_not() -> None:
    messages = check_viewsets()
    assert _ids(messages) == ["karni.W101"]
    (message,) = messages
    assert message.obj is DuplicatingVenueViewSet
    assert "PlainVenueSerializer duplicates the serializer Karni generates from Venue" in (
        message.msg
    )
    assert "APIMeta" in message.hint


def test_schedule_problems_surface_at_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> list[Any]:
        raise ScheduleError("Schedule name 'nightly' is declared twice.", code="E406")

    monkeypatch.setattr("karni.schedule.discover", broken)
    (message,) = check_schedules()
    assert message.id == "karni.E406"
    assert message.msg == "Schedule name 'nightly' is declared twice."
    assert message.hint.endswith(f"See {docs_url('E406')}")


def test_valid_schedules_pass() -> None:
    assert check_schedules() == []
