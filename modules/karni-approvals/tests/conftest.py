"""Shared fixtures for the karni-approvals suite: synced roles, a maker, checkers, rows."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from karni.accounts.permissions import assign_role
from karni.accounts.roles import sync_roles
from karni.celery import create_celery_app

from karni_approvals.meta import clear_caches
from tests.testapp.models import Branch, Invoice

# One Celery app for the whole suite, configured from tests.settings —
# becomes the current app, so shared_task .delay() honours eager mode.
celery_app = create_celery_app("karni-approvals-tests")


@pytest.fixture(autouse=True)
def _roles(db: None) -> None:
    sync_roles()
    clear_caches()


def make_user(email: str, *roles: str, staff: bool = False, superuser: bool = False) -> Any:
    model = get_user_model()
    if superuser:
        return model.objects.create_superuser(email=email, password="s3cret-pass-123")
    user = model.objects.create_user(email=email, password="s3cret-pass-123", is_staff=staff)
    for slug in roles:
        assign_role(user, slug)
    return user


@pytest.fixture
def maker() -> Any:
    return make_user("maker@example.com", "clerk")


@pytest.fixture
def checker() -> Any:
    return make_user("checker@example.com", "finance")


@pytest.fixture
def second_checker() -> Any:
    return make_user("second@example.com", "finance")


@pytest.fixture
def root() -> Any:
    return make_user("root@example.com", superuser=True)


@pytest.fixture
def branch() -> Branch:
    return Branch.objects.create(name="North")


@pytest.fixture
def invoice(branch: Branch) -> Invoice:
    """Created with no current user: unattended code is never held."""
    return Invoice.objects.create(number="INV-1", amount=Decimal("10.00"), branch=branch)
