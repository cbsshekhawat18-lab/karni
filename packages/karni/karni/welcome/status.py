"""The welcome page's status checks: a tick or a cross, plus the command that fixes a cross.

Every check reports presence or absence only — "database reachable", never
which database. A check never raises: an exception is a cross whose detail
names the exception type and nothing else.
"""

from __future__ import annotations

import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connections
from django.db.migrations.executor import MigrationExecutor

from karni.health.checks import check_celery, check_database

__all__ = ["Status", "run_checks"]


@dataclass(frozen=True)
class Status:
    """One line of the status table."""

    key: str
    name: str
    ok: bool
    detail: str
    fix: str = ""
    """The exact command that fixes it; empty when ``ok``."""
    hint: str = ""
    """One short alternative, shown after the command."""


def _guard(fn: Callable[[], tuple[bool, str]]) -> tuple[bool, str]:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - the page reports, it never crashes
        return False, f"check raised {type(exc).__name__}"


def database() -> Status:
    ok, detail = _guard(check_database)
    return Status(
        "database",
        "Database reachable",
        ok,
        detail if ok else "not reachable",
        fix="docker compose up -d db",
        hint="or point DATABASE_URL in .env at a running PostgreSQL",
    )


def migrations() -> Status:
    def probe() -> tuple[bool, str]:
        executor = MigrationExecutor(connections["default"])
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if plan:
            return False, f"{len(plan)} migration(s) not applied"
        return True, "all migrations applied"

    ok, detail = _guard(probe)
    return Status("migrations", "Migrations applied", ok, detail, fix="karni migrate")


def superuser() -> Status:
    def probe() -> tuple[bool, str]:
        exists = get_user_model()._default_manager.filter(is_superuser=True).exists()
        return exists, "a superuser exists" if exists else "no superuser yet"

    ok, detail = _guard(probe)
    return Status("superuser", "Superuser exists", ok, detail, fix="karni createsuperuser")


def seed_data() -> Status:
    def probe() -> tuple[bool, str]:
        from karni.seeding import DEMO_LOGIN

        user_model = get_user_model()
        field = getattr(user_model, "USERNAME_FIELD", "username")
        exists = user_model._default_manager.filter(**{field: DEMO_LOGIN}).exists()
        return exists, "demo data seeded" if exists else "no demo data yet"

    ok, detail = _guard(probe)
    return Status("seed", "Seed data present", ok, detail, fix="karni seed")


def _redis_ping(url: str) -> bool:
    import redis

    client = redis.Redis.from_url(url, socket_connect_timeout=0.5, socket_timeout=0.5)
    try:
        return bool(client.ping())
    finally:
        client.close()


def redis_server() -> Status:
    def probe() -> tuple[bool, str]:
        broker = str(getattr(settings, "CELERY_BROKER_URL", "") or "")
        if broker.startswith(("redis://", "rediss://", "unix://")):
            return _redis_ping(broker), "Redis answering"
        from karni.health.checks import check_cache

        ok, _detail = check_cache()
        return ok, "cache answering (no Redis broker configured)"

    ok, detail = _guard(probe)
    return Status(
        "redis",
        "Redis reachable",
        ok,
        detail if ok else "not reachable",
        fix="docker compose up -d redis",
        hint="or point REDIS_URL in .env at a running Redis",
    )


def celery_worker(redis_ok: bool) -> Status:
    if not redis_ok:
        return Status(
            "celery", "Celery worker responding", False, "needs Redis first", fix="karni worker"
        )
    ok, detail = _guard(check_celery)
    return Status(
        "celery",
        "Celery worker responding",
        ok,
        detail if ok else "no worker replied",
        fix="karni worker",
    )


def _http_alive(url: str) -> bool:
    with urllib.request.urlopen(url, timeout=0.5) as response:  # noqa: S310 - the dev server URL
        return int(response.status) < 500


def frontend() -> Status:
    def probe() -> tuple[bool, str]:
        url = str(getattr(settings, "KARNI_FRONTEND_URL", "") or "")
        if not url:
            return False, "KARNI_FRONTEND_URL is not set"
        return _http_alive(url), "dev server answering"

    ok, detail = _guard(probe)
    return Status(
        "frontend",
        "Frontend dev server running",
        ok,
        detail if ok else "not answering",
        fix="cd frontend && npm run dev",
        hint="after `npm install` once",
    )


def run_checks() -> list[Status]:
    """The seven checks, in the order the page shows them."""
    found = [database(), migrations(), superuser(), seed_data()]
    redis_status = redis_server()
    found.extend([redis_status, celery_worker(redis_status.ok), frontend()])
    return found


def as_dicts(statuses: list[Status]) -> list[dict[str, Any]]:
    """Plain data, for tests and for anything that renders the checks elsewhere."""
    return [status.__dict__ for status in statuses]
