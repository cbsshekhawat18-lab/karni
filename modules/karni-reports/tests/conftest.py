"""Shared fixtures: an owner, another user, staff, a product and a category."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from karni.accounts.permissions import assign_role
from karni.accounts.roles import sync_roles
from karni.celery import create_celery_app
from rest_framework.test import APIClient

from karni_reports.rendering import FakeRenderer
from tests.testapp.models import Category, Product

celery_app = create_celery_app("karni-reports-tests")


@pytest.fixture(autouse=True)
def _fake_renderer() -> Iterator[None]:
    FakeRenderer.reset()
    yield
    FakeRenderer.reset()


@pytest.fixture(autouse=True)
def _roles(db: None) -> None:
    sync_roles()


def make_user(email: str, *roles: str) -> Any:
    user = get_user_model().objects.create_user(email=email, password="s3cret-pass-123")
    for slug in roles:
        assign_role(user, slug)
    return user


@pytest.fixture
def owner() -> Any:
    return make_user("owner@example.com")


@pytest.fixture
def other() -> Any:
    return make_user("other@example.com")


@pytest.fixture
def staff() -> Any:
    return make_user("staff@example.com", "staff")


@pytest.fixture
def category() -> Category:
    return Category.objects.create(name="Lamps")


@pytest.fixture
def product(owner: Any, category: Category) -> Product:
    return Product.objects.create(
        owner=owner, category=category, name="Desk lamp", price=Decimal("49.00")
    )


@pytest.fixture
def client_for() -> Any:
    def _client(user: Any = None) -> APIClient:
        client = APIClient()
        if user is not None:
            client.force_authenticate(user)
        return client

    return _client
