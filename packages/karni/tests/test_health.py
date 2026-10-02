"""Tests for karni.health.

Every test runs without Postgres, Redis or a Celery worker: readiness checks
are pointed at local stand-ins via ``override_settings(KARNI_HEALTH_CHECKS=...)``
or monkeypatched on ``karni.health.checks``, the database check runs against
the sqlite test database and the cache check against LocMemCache.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.http import JsonResponse
from django.test import RequestFactory, override_settings

from karni.health import checks as health_checks
from karni.health import urls as health_urls
from karni.health.views import liveness, readiness


def _path(name: str) -> str:
    """Dotted path to a callable defined in this module, however pytest imported it."""
    return f"{__name__}.{name}"


def _payload(response: JsonResponse) -> dict[str, Any]:
    return json.loads(response.content)


# --- stand-in checks referenced by dotted path -------------------------------


def check_always_ok() -> tuple[bool, str]:
    return True, "all good"


def check_always_fail() -> tuple[bool, str]:
    return False, "broken"


def check_boom() -> tuple[bool, str]:
    raise RuntimeError("kaboom")


def check_bare_exception() -> tuple[bool, str]:
    raise ValueError


def check_database() -> tuple[bool, str]:
    """Local double whose dotted name exercises ``check_`` prefix stripping."""
    return True, "fake db"


def plain_probe() -> tuple[bool, str]:
    """A check without the ``check_`` prefix keeps its full name."""
    return True, "plain"


# --- liveness ----------------------------------------------------------------


def test_liveness_returns_ok() -> None:
    response = liveness(RequestFactory().get("/health/"))
    assert response.status_code == 200
    assert _payload(response) == {"status": "ok"}


# --- readiness ---------------------------------------------------------------


@override_settings(KARNI_HEALTH_CHECKS=[_path("check_always_ok"), _path("plain_probe")])
def test_readiness_all_ok_returns_200() -> None:
    response = readiness(RequestFactory().get("/health/ready/"))
    assert response.status_code == 200
    payload = _payload(response)
    assert payload["status"] == "ok"
    assert payload["checks"] == {
        "always_ok": {"ok": True, "detail": "all good"},
        "plain_probe": {"ok": True, "detail": "plain"},
    }


@override_settings(KARNI_HEALTH_CHECKS=[_path("check_always_ok"), _path("check_always_fail")])
def test_readiness_aggregates_and_returns_503_on_any_failure() -> None:
    response = readiness(RequestFactory().get("/health/ready/"))
    assert response.status_code == 503
    payload = _payload(response)
    assert payload["status"] == "fail"
    assert payload["checks"]["always_ok"] == {"ok": True, "detail": "all good"}
    assert payload["checks"]["always_fail"] == {"ok": False, "detail": "broken"}


@override_settings(KARNI_HEALTH_CHECKS=[_path("check_boom")])
def test_readiness_turns_exception_into_failed_check() -> None:
    # Must not raise: the exception becomes a failed check with its text as detail.
    response = readiness(RequestFactory().get("/health/ready/"))
    assert response.status_code == 503
    payload = _payload(response)
    assert payload["status"] == "fail"
    assert payload["checks"]["boom"] == {"ok": False, "detail": "kaboom"}


@override_settings(KARNI_HEALTH_CHECKS=[_path("check_bare_exception")])
def test_readiness_uses_exception_class_when_message_empty() -> None:
    response = readiness(RequestFactory().get("/health/ready/"))
    assert response.status_code == 503
    assert _payload(response)["checks"]["bare_exception"] == {
        "ok": False,
        "detail": "ValueError",
    }


@override_settings(KARNI_HEALTH_CHECKS=["karni.health.checks.does_not_exist"])
def test_readiness_bad_dotted_path_is_failed_check_not_crash() -> None:
    response = readiness(RequestFactory().get("/health/ready/"))
    assert response.status_code == 503
    payload = _payload(response)
    entry = payload["checks"]["does_not_exist"]
    assert entry["ok"] is False
    assert "does_not_exist" in entry["detail"]


@override_settings(KARNI_HEALTH_CHECKS=[_path("check_database")])
def test_readiness_strips_check_prefix_from_names() -> None:
    response = readiness(RequestFactory().get("/health/ready/"))
    assert _payload(response)["checks"] == {"database": {"ok": True, "detail": "fake db"}}


def test_readiness_runs_default_checks_via_dotted_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default dotted paths resolve live module attributes, so monkeypatched
    checks are picked up and no real Postgres/Redis/Celery is contacted."""
    monkeypatch.setattr(health_checks, "check_database", check_always_ok)
    monkeypatch.setattr(health_checks, "check_cache", check_always_ok)
    monkeypatch.setattr(health_checks, "check_celery", check_always_fail)
    with override_settings(KARNI_HEALTH_CHECKS=list(health_checks.DEFAULT_HEALTH_CHECKS)):
        response = readiness(RequestFactory().get("/health/ready/"))
    assert response.status_code == 503
    payload = _payload(response)
    assert set(payload["checks"]) == {"database", "cache", "celery"}
    assert payload["checks"]["database"]["ok"] is True
    assert payload["checks"]["cache"]["ok"] is True
    assert payload["checks"]["celery"] == {"ok": False, "detail": "broken"}


# --- individual checks -------------------------------------------------------


@pytest.mark.django_db
def test_check_database_succeeds_against_test_database() -> None:
    ok, detail = health_checks.check_database()
    assert ok is True
    assert detail == "database responding"


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
def test_check_cache_roundtrip_with_locmem() -> None:
    ok, detail = health_checks.check_cache()
    assert ok is True
    assert detail == "cache responding"


class _FakeControl:
    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = replies
        self.seen_timeout: float | None = None

    def ping(self, timeout: float) -> list[dict[str, Any]]:
        self.seen_timeout = timeout
        return self.replies


class _FakeCeleryApp:
    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.control = _FakeControl(replies)


def test_check_celery_honours_timeout_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _FakeCeleryApp([{"worker@host": {"ok": "pong"}}])
    monkeypatch.setattr(health_checks, "current_app", app)
    with override_settings(KARNI_HEALTH_CELERY_TIMEOUT=2.5):
        ok, detail = health_checks.check_celery()
    assert ok is True
    assert app.control.seen_timeout == 2.5
    assert "1 worker(s) replied" == detail


def test_check_celery_fails_without_pong(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _FakeCeleryApp([])
    monkeypatch.setattr(health_checks, "current_app", app)
    with override_settings(KARNI_HEALTH_CELERY_TIMEOUT=0.1):
        ok, detail = health_checks.check_celery()
    assert ok is False
    assert "no Celery worker replied" in detail
    assert app.control.seen_timeout == 0.1


# --- urls --------------------------------------------------------------------


def test_urls_module_names_and_order() -> None:
    assert health_urls.app_name == "karni_health"
    assert [pattern.name for pattern in health_urls.urlpatterns] == [
        "liveness",
        "readiness",
    ]
    assert health_urls.urlpatterns[0].callback is liveness
    assert health_urls.urlpatterns[1].callback is readiness
