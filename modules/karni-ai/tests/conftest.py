"""Shared fixtures for the karni-ai suite: synced roles, an editor and a reader, catalog rows."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from karni.accounts.permissions import assign_role
from karni.accounts.roles import sync_roles
from karni.celery import create_celery_app
from rest_framework.test import APIClient

from karni_ai.providers.test import TestProvider
from tests.testapp.models import Category, Tag

# One Celery app for the whole suite, configured from tests.settings: the
# import's preview runs inline anyway (small files), eager when it is not.
celery_app = create_celery_app("karni-ai-tests")

PRODUCTS = """Name: Garden hose
SKU: GH-100
Price: 19.90
Stock: 12
Status: active
Category: Garden
Tags: outdoor, water

Name: Rake
SKU: RK-200
Price: 24.50
Category: Garden
"""


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    """A fresh test provider and throttle history for every test."""
    TestProvider.reset()
    cache.clear()
    yield
    TestProvider.reset()


@pytest.fixture(autouse=True)
def _roles(db: None) -> None:
    sync_roles()


def make_user(email: str, *roles: str) -> Any:
    user = get_user_model().objects.create_user(email=email, password="s3cret-pass-123")
    for slug in roles:
        assign_role(user, slug)
    return user


@pytest.fixture
def editor() -> Any:
    return make_user("editor@example.com", "editor")


@pytest.fixture
def reader() -> Any:
    """Reads products, creates categories, never creates products."""
    return make_user("reader@example.com", "buyer")


@pytest.fixture
def catalog(db: None) -> None:
    Category.objects.create(name="Garden")
    Tag.objects.create(name="outdoor")
    Tag.objects.create(name="water")


@pytest.fixture
def client_for() -> Any:
    def _client(user: Any = None) -> APIClient:
        client = APIClient()
        if user is not None:
            client.force_authenticate(user)
        return client

    return _client


@pytest.fixture
def editor_client(editor: Any, client_for: Any) -> APIClient:
    client: APIClient = client_for(editor)
    return client
