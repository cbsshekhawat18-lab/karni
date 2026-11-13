"""Fixtures for the demo's tests: demo mode on, a stamp in tmp_path, seeded data."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from django.core.cache import cache
from django.test import Client

from karni.demo import accounts, reset

STAFF = "demo@example.com"
CUSTOMER = "customer@example.com"  # the second demo account
OTHER = "visitor@example.com"  # an account that is not a demo account
PASSWORD = "karni-password"


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    """Sign-in throttles and the terms answers live in the cache: each test starts empty."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def demo(settings: Any, tmp_path: Path) -> Any:
    """Demo mode on, the reset stamp in tmp_path, a reset check on every request."""
    settings.KARNI_DEMO_MODE = True
    settings.KARNI_DEMO_RESET_STAMP = str(tmp_path / "demo-reset.json")
    settings.KARNI_DEMO_RESET_CHECK_SECONDS = 0
    settings.KARNI_SEED_LOGINS = {OTHER: ["customer"]}
    return settings


@pytest.fixture
def seeded(demo: Any, db: None) -> dt.datetime:
    """The database as the first boot leaves it. Returns the stamp's time."""
    reset.boot()
    found = reset.last_reset()
    assert found is not None
    return found


def user_of(login: str) -> Any:
    """The account with this login, which the seed or the boot made."""
    user = accounts.find(login)
    assert user is not None
    return user


def demo_user() -> Any:
    """The staff demo account, which the seed made."""
    return user_of(STAFF)


def write_stamp(when: dt.datetime) -> None:
    reset.stamp_path().write_text(json.dumps({"reset_at": when.isoformat(), "seed": 42}))


def token(client: Client, email: str) -> str:
    """Sign in through the API: the access token."""
    answer = client.post(
        "/api/auth/login/",
        {"email": email, "password": PASSWORD},
        content_type="application/json",
    )
    assert answer.status_code == 200, answer.content
    return str(answer.json()["access"])


def bearer(access: str) -> dict[str, str]:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}
