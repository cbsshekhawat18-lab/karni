"""Shared fixtures for the karni-commerce suite: roles, people, things to sell and helpers."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone
from karni.accounts.roles import sync_roles
from karni.celery import create_celery_app
from karni.testing import user_with_roles
from karni_payments.providers.test import TestProvider
from karni_payments.test_checkout import settle as settle_payment
from rest_framework.test import APIClient

from karni_commerce import services
from karni_commerce.models import Cart, Order
from tests.testapp.models import Gadget, Slot, Workshop

celery_app = create_celery_app("karni-commerce-tests")

ADDRESS = {
    "name": "Ines Moreau",
    "line1": "4 Rue des Lilas",
    "city": "Lyon",
    "postcode": "69001",
    "country": "FR",
}


@pytest.fixture(autouse=True)
def _setup(db: None) -> Iterator[None]:
    sync_roles()
    TestProvider.reset()
    yield
    TestProvider.reset()


@pytest.fixture
def buyer() -> Any:
    return user_with_roles("customer", email="ines@example.com")


@pytest.fixture
def other() -> Any:
    return user_with_roles("customer", email="noor@example.com")


@pytest.fixture
def clerk() -> Any:
    return user_with_roles("clerk", email="clerk@example.com")


@pytest.fixture
def manager() -> Any:
    return user_with_roles("manager", email="manager@example.com")


@pytest.fixture
def api() -> APIClient:
    return APIClient()


@pytest.fixture
def make_gadget() -> Callable[..., Gadget]:
    def make(**values: Any) -> Gadget:
        values = {"name": "Lamp", "sku": "LMP-1", "price": Decimal("20.00"), "stock": 5, **values}
        return Gadget.objects.create(**values)

    return make


@pytest.fixture
def make_workshop() -> Callable[..., Workshop]:
    def make(**values: Any) -> Workshop:
        values = {
            "title": "Pottery basics",
            "price": Decimal("45.00"),
            "seats": 4,
            "starts_at": timezone.now() + timedelta(days=7),
            **values,
        }
        return Workshop.objects.create(**values)

    return make


@pytest.fixture
def make_slot() -> Callable[..., Slot]:
    def make(**values: Any) -> Slot:
        values = {
            "title": "Consultation",
            "price": Decimal("50.00"),
            "deposit": Decimal("10.00"),
            "seats": 1,
            "starts_at": timezone.now() + timedelta(days=7),
            **values,
        }
        return Slot.objects.create(**values)

    return make


def cart_with(*lines: tuple[str, Any, int]) -> Cart:
    """A visitor's cart holding ``(kind, item, quantity)`` lines."""
    cart = Cart.objects.create()
    for kind, item, quantity in lines:
        services.set_line(cart, kind, str(item.pk), quantity)
    return cart


def place(
    cart: Cart, email: str = "guest@example.com", user: Any = None, *, deposit: bool = False
) -> Order:
    return services.checkout(
        cart, user=user, email=email, billing=ADDRESS, shipping=ADDRESS, deposit=deposit
    )


def pay(order: Order, outcome: str = "pay") -> Order:
    """Open the order's payment and settle it at the test provider's page."""
    services.open_payment(order)
    link = order.payments.order_by("-created_at").first()
    assert link is not None
    settle_payment(link.payment, outcome)
    order.refresh_from_db()
    return order


def refund_webhook(order: Order, status: str = "refund_succeeded") -> None:
    """The provider's word that the order's pending refunds went through (or failed)."""
    from karni_payments.models import WebhookEvent
    from karni_payments.tasks import process_webhook_event

    link = order.payments.order_by("-created_at").first()
    assert link is not None
    payment = link.payment
    payment.refresh_from_db()
    event = WebhookEvent.objects.create(
        provider="test",
        event_id=f"evt_{WebhookEvent.objects.count()}",
        event_type="refund",
        payload={
            "type": "refund",
            "status": status,
            "checkout_session_id": payment.checkout_session_id,
        },
    )
    process_webhook_event(str(event.pk))
