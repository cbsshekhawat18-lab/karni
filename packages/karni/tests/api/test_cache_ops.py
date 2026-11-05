"""Response caching in operation: the check rule, clearing, the flush, the admin screen."""

from __future__ import annotations

import fnmatch
import importlib
from collections.abc import Callable, Iterator
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from celery.schedules import crontab
from django.contrib.auth import get_user_model
from django.core.cache import cache as default_cache
from django.core.cache.backends.locmem import LocMemCache
from django.core.exceptions import ImproperlyConfigured
from django.test import Client
from django.test.utils import override_settings
from django.utils import timezone
from django_celery_beat.tzcrontab import TzAwareCrontab
from rest_framework.test import APIRequestFactory

from karni.api import Access, BaseViewSet, Cache, HasRole, Public, Uncached
from karni.api.caching import FlushTime, clear, parse_flush
from karni.api.routers import KarniRouter
from karni.checks import check_api_cache, check_api_cache_backend
from karni.conf.validation import validate_settings
from karni.exceptions import KarniImproperlyConfigured
from karni.tasks import flush_api_cache
from tests.externalapp.viewsets import (
    ProductMappingViewSet,
    RegionViewSet,
    SaleViewSet,
    StockViewSet,
)
from tests.testapp.models import Event, Venue

pytestmark = pytest.mark.django_db

OPEN = Access(read=Public(), write=HasRole("staff"))


class Events(BaseViewSet):
    model = Event
    access = OPEN
    auto_register = False


class Venues(BaseViewSet):
    model = Venue
    access = OPEN
    auto_register = False


class BoundedSales(SaleViewSet):
    cache = Cache(ttl=60)


class UncachedStock(StockViewSet):
    cache = Uncached(reason="the warehouse writes it")


def cache_router() -> KarniRouter:
    """The router of the E410 test: two problems, two accepted ones, one plain resource."""
    router = KarniRouter()
    router.register("regions", RegionViewSet, basename="regions")
    router.register("mappings", ProductMappingViewSet, basename="mappings")
    router.register("sales", BoundedSales, basename="sales")
    router.register("stock", UncachedStock, basename="stock")
    router.register("venues", Venues, basename="venues")
    return router


class PatternCache(LocMemCache):
    """A local cache with django-redis's ``delete_pattern``."""

    def delete_pattern(self, pattern: str) -> int:
        made = self.make_key(pattern)
        with self._lock:
            doomed = [key for key in list(self._cache) if fnmatch.fnmatchcase(key, made)]
            for key in doomed:
                self._delete(key)
        return len(doomed)


PATTERNED = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "t"},
    "patterned": {"BACKEND": "tests.api.test_cache_ops.PatternCache", "LOCATION": "p"},
}


@pytest.fixture(autouse=True)
def _cache_on() -> Iterator[None]:
    default_cache.clear()
    with override_settings(KARNI_API_CACHE=True):
        yield
    default_cache.clear()


@pytest.fixture
def event() -> Event:
    venue = Venue.objects.create(name="Arena", city="Lyon")
    return Event.objects.create(title="One", starts_at=timezone.now(), venue=venue)


def _get(viewset: type[Any]) -> Any:
    return viewset.as_view({"get": "list"})(APIRequestFactory().get("/"))


# the check rule


def test_e410_names_each_cached_viewset_that_reads_what_nothing_invalidates() -> None:
    with override_settings(KARNI_API_ROUTER="tests.api.test_cache_ops.cache_router"):
        messages = check_api_cache()
        assert sorted((m.id, m.obj.__name__) for m in messages) == [
            ("karni.E410", "ProductMappingViewSet"),
            ("karni.E410", "RegionViewSet"),
        ]
        by_name = {m.obj.__name__: m.msg for m in messages}
        assert "externalapp.Region (external" in by_name["RegionViewSet"]
        assert "on the database 'second'" in by_name["ProductMappingViewSet"]
        assert "Cache(ttl=60)" in messages[0].hint
        with override_settings(KARNI_API_CACHE=False):
            assert check_api_cache() == []


def test_w580_warns_about_a_cache_private_to_each_process() -> None:
    with override_settings(DEBUG=False):
        assert [m.id for m in check_api_cache_backend()] == ["karni.W580"]
        with override_settings(KARNI_API_CACHE=False):
            assert check_api_cache_backend() == []
    with override_settings(DEBUG=True):
        assert check_api_cache_backend() == []


# clearing


def test_clear_uses_delete_pattern_when_the_backend_has_it(event: Event) -> None:
    with override_settings(CACHES=PATTERNED, KARNI_API_CACHE_ALIAS="patterned"):
        _get(Events), _get(Venues)
        assert clear(Event) == "delete_pattern"
        assert (_get(Events)["X-Cache"], _get(Venues)["X-Cache"]) == ("MISS", "HIT")
        assert clear() == "delete_pattern"
        assert (_get(Events)["X-Cache"], _get(Venues)["X-Cache"]) == ("MISS", "MISS")


def test_clear_replaces_the_version_tokens_otherwise(event: Event) -> None:
    _get(Events), _get(Venues)
    assert clear("testapp.Venue") == "versions"
    # Events reads Venue too (?expand= and the plan), the plain venue list of course.
    assert _get(Venues)["X-Cache"] == "MISS"
    assert clear() == "versions"
    assert (_get(Events)["X-Cache"], _get(Venues)["X-Cache"]) == ("MISS", "MISS")


def test_the_flush_task_clears_everything(event: Event) -> None:
    _get(Events)
    assert flush_api_cache() == "versions"
    assert _get(Events)["X-Cache"] == "MISS"


# the scheduled flush


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        ("03:30", FlushTime(3, 30)),
        (" 23:05 Europe/Paris ", FlushTime(23, 5, "Europe/Paris")),
    ],
)
def test_the_flush_setting_parses(value: Any, expected: FlushTime | None) -> None:
    assert parse_flush(value) == expected


@pytest.mark.parametrize("value", ["25:00", "3pm", "03:30 Mars/Base", 330])
def test_a_flush_setting_that_is_not_a_time_is_refused(value: Any) -> None:
    with pytest.raises(KarniImproperlyConfigured, match="KARNI_API_CACHE_FLUSH") as error:
        parse_flush(value)
    assert error.value.code == "E411"


def test_settings_validation_reports_a_bad_flush(make_settings: Callable[..., Any]) -> None:
    namespace = make_settings("dev", DEBUG=True, KARNI_API_CACHE_FLUSH="noon")
    with pytest.raises(ImproperlyConfigured, match="E411"):
        validate_settings(namespace)


def _declared(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Run karni/schedules.py again into a fresh registry, as discovery would."""
    from karni import schedule

    fresh = schedule.ScheduleRegistry()
    monkeypatch.setattr(schedule, "registry", fresh)
    monkeypatch.setattr(schedule, "_default_registry", fresh)
    from karni import schedules

    importlib.reload(schedules)
    return fresh.entries()


def test_the_flush_is_scheduled_in_its_timezone(
    monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    settings.KARNI_API_CACHE_FLUSH = "03:30 Europe/Paris"
    (entry,) = _declared(monkeypatch)
    assert (entry.name, entry.task) == ("karni-flush-api-cache", "karni.tasks.flush_api_cache")
    assert isinstance(entry.schedule, TzAwareCrontab)
    assert entry.schedule.tz == ZoneInfo("Europe/Paris")
    assert (entry.schedule.hour, entry.schedule.minute) == ({3}, {30})
    assert entry.timing == "daily at 03:30 (Europe/Paris)"
    settings.KARNI_API_CACHE_FLUSH = "04:00"
    (entry,) = _declared(monkeypatch)
    assert type(entry.schedule) is crontab and entry.schedule.hour == {4}


def test_the_flush_is_off_by_default(monkeypatch: pytest.MonkeyPatch, settings: Any) -> None:
    assert _declared(monkeypatch) == []
    settings.KARNI_API_CACHE_FLUSH = "03:30"
    settings.KARNI_API_CACHE = False
    assert _declared(monkeypatch) == []


# the admin screen


SCREEN = "/admin/karni/api-cache/"


def _client(**flags: Any) -> Client:
    users = get_user_model()
    if flags.pop("superuser", False):
        user = users.objects.create_superuser(email="root@example.com", password="pw-123456789")
    else:
        user = users.objects.create_user(
            email="staff@example.com", password="pw-123456789", **flags
        )
    client = Client()
    client.force_login(user)
    return client


def test_the_screen_shows_the_setup_and_the_resources(settings: Any) -> None:
    settings.KARNI_API_CACHE_FLUSH = "03:30 Europe/Paris"
    client = _client(superuser=True)
    page = client.get(SCREEN)
    assert page.status_code == 200
    text = page.content.decode()
    assert "LocMemCache" in text and "no delete_pattern" in text
    assert "daily at 03:30 (Europe/Paris)" in text
    assert "testapp.Event" in text and "Clear everything" in text
    assert SCREEN in client.get("/admin/").content.decode()  # listed on the index


def test_the_screen_clears_everything_or_one_resource(event: Event) -> None:
    client = _client(superuser=True)
    _get(Events)
    response = client.post(SCREEN, {"clear": "all"}, follow=True)
    assert "Cleared every cached response (versions)." in response.content.decode()
    assert _get(Events)["X-Cache"] == "MISS"
    response = client.post(SCREEN, {"clear": "testapp.Event"}, follow=True)
    assert "Cleared the cached responses of testapp.Event" in response.content.decode()
    assert _get(Events)["X-Cache"] == "MISS"
    response = client.post(SCREEN, {"clear": "nope.Model"}, follow=True)
    assert "No model is called nope.Model." in response.content.decode()


def test_only_superusers_see_the_screen() -> None:
    client = _client(is_staff=True)
    assert client.get(SCREEN).status_code == 403
    assert client.post(SCREEN, {"clear": "all"}).status_code == 403
    assert SCREEN not in client.get("/admin/").content.decode()


# tests start from an empty cache


def test_turning_caching_on_starts_from_no_cached_response(event: Event) -> None:
    _get(Events)
    assert _get(Events)["X-Cache"] == "HIT"
    with override_settings(KARNI_API_CACHE=True):  # a test of its own would do this
        assert _get(Events)["X-Cache"] == "MISS"


def test_the_pytest_plugin_empties_the_cache_before_each_test(event: Event) -> None:
    from karni.testing import pytest_plugin

    _get(Events)
    pytest_plugin._karni_fresh_response_cache.__wrapped__()  # type: ignore[attr-defined]
    assert _get(Events)["X-Cache"] == "MISS"
