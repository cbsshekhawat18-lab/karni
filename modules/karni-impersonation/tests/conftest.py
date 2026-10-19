"""Shared fixtures: synced roles, a support user, a customer, a finance user."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from karni.accounts.permissions import assign_role
from karni.accounts.roles import sync_roles
from karni.celery import create_celery_app

from karni_impersonation.models import ImpersonationSession
from tests.testapp.models import Note

celery_app = create_celery_app("karni-impersonation-tests")


@pytest.fixture(autouse=True)
def _roles(db: None) -> None:
    sync_roles()


def make_user(email: str, *roles: str, staff: bool = False, superuser: bool = False) -> Any:
    model = get_user_model()
    if superuser:
        return model.objects.create_superuser(email=email, password="s3cret-pass-123")
    user = model.objects.create_user(email=email, password="s3cret-pass-123", is_staff=staff)
    for slug in roles:
        assign_role(user, slug)
    return user


def grant_admin_perms(user: Any) -> Any:
    """Django's model permissions for the admin screens (the grants decide the rows)."""
    user.user_permissions.add(
        *Permission.objects.filter(
            content_type__in=[
                ContentType.objects.get_for_model(Note),
                ContentType.objects.get_for_model(ImpersonationSession),
                ContentType.objects.get_for_model(get_user_model()),
            ]
        )
    )
    return user


@pytest.fixture
def support() -> Any:
    return grant_admin_perms(make_user("support@example.com", "support", staff=True))


@pytest.fixture
def customer() -> Any:
    return make_user("customer@example.com", "customer")


@pytest.fixture
def finance() -> Any:
    return make_user("finance@example.com", "finance", "customer")
