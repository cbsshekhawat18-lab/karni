"""Shared set-up for the karni-site suite: a clean cache, media in a temporary folder,
synced roles and the people who edit, and one Celery app for the queued listener."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from karni.accounts.permissions import assign_role
from karni.accounts.roles import sync_roles
from karni.celery import create_celery_app
from pytest_django import Settings

# One Celery app for the suite, configured from tests.settings. It becomes the current app,
# so the queued listener's shared task honours CELERY_TASK_ALWAYS_EAGER.
celery_app = create_celery_app("karni-site-tests")


@pytest.fixture(autouse=True)
def _clean_cache() -> Iterator[None]:
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _media(settings: Settings, tmp_path: Path) -> None:
    settings.MEDIA_ROOT = str(tmp_path / "media")


@pytest.fixture
def roles(db: None) -> None:
    sync_roles()


def make_user(email: str, *roles: str, staff: bool = False, superuser: bool = False) -> Any:
    model = get_user_model()
    if superuser:
        return model.objects.create_superuser(email=email, password="s3cret-pass-123")
    user = model.objects.create_user(email=email, password="s3cret-pass-123", is_staff=staff)
    for slug in roles:
        assign_role(user, slug)
    return user


@pytest.fixture
def editor(roles: None) -> Any:
    return make_user("editor@example.com", "editor", staff=True)


@pytest.fixture
def owner(db: None) -> Any:
    return make_user("owner@example.com", superuser=True)
