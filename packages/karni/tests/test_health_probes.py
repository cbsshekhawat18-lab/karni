"""``/healthz`` and ``/readyz`` (experimental): each dependency failing in turn and the exemptions.

No service runs: the cache is LocMemCache, the database is the SQLite test database and the
Celery broker is Celery's in-memory transport. A dependency "fails" by being replaced with one
that raises, or by pointing the broker at a closed port.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any

import pytest
import structlog
from celery import current_app
from django.core.cache import cache
from django.db import OperationalError
from django.test import Client
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from karni.conf.logging import DEFAULT_QUIET_PATHS, QuietPaths, build_logging
from karni.health import checks as health_checks

pytestmark = pytest.mark.django_db

CHECKS = ["database", "cache", "broker"]


@pytest.fixture(autouse=True)
def _memory_broker(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setitem(current_app.conf, "broker_url", "memory://")
    yield


def _fail_database(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken:
        def cursor(self) -> Any:
            raise OperationalError("connection refused")

    monkeypatch.setattr(health_checks, "connections", {"default": Broken()})


def _fail_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken:
        def set(self, *args: Any, **kwargs: Any) -> None:
            raise ConnectionError("redis is down")

    monkeypatch.setattr(health_checks, "cache", Broken())


def _fail_broker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(current_app.conf, "broker_url", "redis://127.0.0.1:1/0")


FAILURES = {"database": _fail_database, "cache": _fail_cache, "broker": _fail_broker}


def test_healthz_answers_without_touching_a_service(
    client: Client, django_assert_num_queries: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    for fail in FAILURES.values():
        fail(monkeypatch)
    with django_assert_num_queries(0):
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_is_200_with_one_entry_per_check(client: Client) -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["failing"] == []
    assert list(body["checks"]) == CHECKS
    assert all(entry["ok"] for entry in body["checks"].values())


@pytest.mark.parametrize("failing", CHECKS)
def test_readyz_is_503_and_names_the_failing_check(
    client: Client, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    FAILURES[failing](monkeypatch)
    response = client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "fail"
    assert body["failing"] == [failing]
    assert body["checks"][failing]["ok"] is False
    assert body["checks"][failing]["detail"]
    assert [name for name, entry in body["checks"].items() if entry["ok"]] == [
        name for name in CHECKS if name != failing
    ]


def test_readyz_checks_are_a_setting(client: Client, settings: Any) -> None:
    settings.KARNI_READYZ_CHECKS = ["karni.health.checks.check_database"]
    assert list(client.get("/readyz").json()["checks"]) == ["database"]


def test_a_check_that_stalls_fails_at_the_timeout(client: Client, settings: Any) -> None:
    settings.KARNI_HEALTH_TIMEOUT = 0.2
    settings.KARNI_READYZ_CHECKS = [f"{__name__}.check_stalls"]
    started = time.monotonic()
    response = client.get("/readyz")
    assert time.monotonic() - started < 2
    assert response.status_code == 503
    assert response.json()["checks"]["stalls"]["detail"] == "no answer within 0.2s"


def check_stalls() -> tuple[bool, str]:
    time.sleep(1.5)
    return True, "late"


def test_the_older_readiness_view_has_the_timeout_and_failing_too(
    client: Client, settings: Any
) -> None:
    settings.KARNI_HEALTH_CHECKS = [f"{__name__}.check_denied"]
    body = client.get("/health/ready/").json()
    assert body["failing"] == ["denied"]


def check_denied() -> tuple[bool, str]:
    return False, "no"


@pytest.mark.parametrize("path", ["/healthz", "/readyz", "/health/", "/health/ready/"])
def test_probes_are_never_cached(client: Client, path: str) -> None:
    cache_control = client.get(path)["Cache-Control"]
    assert "no-store" in cache_control
    assert "max-age=0" in cache_control


@pytest.mark.parametrize("path", ["/healthz", "/readyz", "/health/ready/"])
def test_probes_are_open_before_the_terms_are_accepted(
    settings: Any, django_user_model: Any, path: str
) -> None:
    # The gate covers the whole site, and this user has accepted nothing.
    settings.KARNI_AUTH_MODE = "jwt"
    settings.KARNI_TERMS = {"version": "2026-11", "url": "/terms/", "paths": ["/"]}
    user = django_user_model.objects.create_user(email="p@example.com", password="x-pass-12345")
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    assert api.get("/api/events/").status_code == 403  # the gate is on
    assert api.get(path).status_code != 403  # /health/ready/ is 503 here: no worker answers


def test_probes_are_not_throttled(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    from rest_framework.throttling import SimpleRateThrottle

    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "anon", "1/min")
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "user", "1/min")
    assert {client.get(path).status_code for path in ["/healthz", "/readyz"] * 15} == {200}


def test_probes_do_not_use_the_response_cache(client: Client) -> None:
    cache.clear()
    client.get("/readyz")
    client.get("/healthz")
    assert cache.get("karni-health") == "ok"  # the check ran, nothing cached the page


# the request log


def _event(request: str, event: str = "request_started", **extra: Any) -> dict[str, Any]:
    return {"event": event, "request": request, **extra}


@pytest.mark.parametrize("path", ["/healthz", "/readyz", "/health/", "/health/ready/?x=1"])
def test_quiet_paths_drop_the_request_lines(path: str) -> None:
    quiet = QuietPaths(DEFAULT_QUIET_PATHS)
    for event in ("request_started", "request_finished"):
        with pytest.raises(structlog.DropEvent):
            quiet(None, "info", _event(f"GET {path}", event, code=200))


def test_other_paths_and_failures_are_still_logged() -> None:
    quiet = QuietPaths(DEFAULT_QUIET_PATHS)
    assert quiet(None, "info", _event("GET /api/events/", "request_finished", code=200))
    assert quiet(None, "info", _event("GET /readyz", "request_finished", code=503))
    assert quiet(None, "info", {"event": "something_else", "request": "GET /readyz"})
    assert QuietPaths(())(None, "info", _event("GET /readyz", code=200))


def test_the_request_log_is_quiet_for_a_probe(
    client: Client, caplog: pytest.LogCaptureFixture
) -> None:
    build_logging(json=True)  # the structlog chain karni_settings() configures
    with caplog.at_level(logging.INFO):
        client.get("/healthz")
        client.get("/api/events/")
    lines = [str(record.msg) for record in caplog.records if "request_" in str(record.msg)]
    assert any("/api/events/" in line for line in lines)
    assert not any("/healthz" in line for line in lines)
