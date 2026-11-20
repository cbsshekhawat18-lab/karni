"""Fixtures for the demo mode tests: demo mode on, two accounts, a stamp in tmp_path."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from django.core.cache import cache
from django.test import Client

from karni.demo import accounts, conf, reset

STAFF = "demo@example.com"
CUSTOMER = "customer@example.com"
OUTSIDER = "visitor@example.com"
JSON = "application/json"

ACCOUNTS = [
    {
        "login": STAFF,
        "label": "Staff",
        "can": "Everything.",
        "roles": "all",
        "staff": True,
        "superuser": True,
    },
    {"login": CUSTOMER, "label": "Customer", "can": "Place orders.", "roles": ["customer"]},
]


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    """Sign-in throttles and the terms answers live in the cache: each test starts empty."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def demo(settings: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Demo mode on, the stamp in tmp_path, a reset check on every request, the test URLs."""
    from django.contrib import admin

    # What startup does when demo mode is on (karni.demo.apps): the admin lists the accounts.
    monkeypatch.setattr(admin.site, "login_template", "demo/admin_login.html")
    settings.ROOT_URLCONF = "tests.demo.urls"
    settings.KARNI_DEMO_MODE = True
    settings.KARNI_DEMO_ACCOUNTS = ACCOUNTS
    settings.KARNI_DEMO_SEEDER = "tests.demo.helpers.seed_venues"
    settings.KARNI_DEMO_RESET_STAMP = str(tmp_path / "demo-reset.json")
    settings.KARNI_DEMO_RESET_CHECK_SECONDS = 0
    return settings


@pytest.fixture
def seeded(demo: Any, db: None) -> dt.datetime:
    """The database as the first boot leaves it. Returns the stamp's time."""
    reset.boot()
    found = reset.last_reset()
    assert found is not None
    return found


def user(login: str) -> Any:
    found = accounts.find(login)
    assert found is not None
    return found


def write_stamp(when: dt.datetime) -> None:
    reset.stamp_path().write_text(json.dumps({"reset_at": when.isoformat(), "seed": 42}))


def token(client: Client, login: str, password: str | None = None) -> str:
    """Sign in through the API: the access token."""
    account = conf.find_account(login)
    secret = password or (account.secret if account else "karni-password")
    answer = client.post(
        "/api/auth/login/", {"email": login, "password": secret}, content_type=JSON
    )
    assert answer.status_code == 200, answer.content
    return str(answer.json()["access"])


def bearer(access: str) -> dict[str, str]:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def make_outsider() -> Any:
    """An account that is not a demo account (a visitor who somehow has one)."""
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email=OUTSIDER, password="a-long-password-1", is_staff=True, is_superuser=True
    )
