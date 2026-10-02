"""Shared fixtures for the karni-payments test suite."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.test import Client
from karni.accounts.permissions import assign_role
from karni.celery import create_celery_app
from rest_framework.test import APIClient

from karni_payments.models import Payment
from karni_payments.providers.test import TestProvider
from karni_payments.viewsets import PAYMENTS_ADMIN_ROLE

# One Celery app for the whole suite, configured from tests.settings —
# becomes the current app, so shared_task .delay() honours eager mode.
celery_app = create_celery_app("karni-payments-tests")

PaymentFactory = Callable[..., Payment]

#: The suite's default redirect targets — KARNI_FRONTEND_URL's origin.
SUCCESS_URL = "http://localhost:5173/checkout/success"
CANCEL_URL = "http://localhost:5173/checkout/cancel"


@pytest.fixture(autouse=True)
def _reset_test_provider() -> Iterator[None]:
    """Deterministic TestProvider ids/state for every test."""
    TestProvider.reset()
    yield
    TestProvider.reset()


@pytest.fixture
def user(db: None) -> AbstractBaseUser:
    return get_user_model().objects.create_user(email="buyer@example.com", password="pw")


@pytest.fixture
def other_user(db: None) -> AbstractBaseUser:
    return get_user_model().objects.create_user(email="other@example.com", password="pw")


@pytest.fixture
def admin_user(db: None) -> AbstractBaseUser:
    admin = get_user_model().objects.create_user(email="admin@example.com", password="pw")
    assign_role(admin, PAYMENTS_ADMIN_ROLE)
    return admin


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def make_payment(db: None, user: AbstractBaseUser) -> PaymentFactory:
    """Create a Payment row directly (provider ``test``, defaults overridable)."""

    def _make(**overrides: Any) -> Payment:
        fields: dict[str, Any] = {
            "user": user,
            "amount": Decimal("100.00"),
            "currency": "usd",
            "provider": "test",
            "status": Payment.Status.PENDING,
        }
        fields.update(overrides)
        return Payment.objects.create(**fields)

    return _make


@pytest.fixture
def deliver_webhook(client: Client) -> Callable[..., Any]:
    """POST a signed TestProvider webhook to the module's webhook endpoint."""

    def _deliver(event: dict[str, Any], *, provider: str = "test", sign: bool = True) -> Any:
        body, headers = TestProvider.build_webhook(event)
        if not sign:
            headers = {}
        return client.post(
            f"/payments/webhook/{provider}/",
            data=body,
            content_type="application/json",
            headers=headers,
        )

    return _deliver
