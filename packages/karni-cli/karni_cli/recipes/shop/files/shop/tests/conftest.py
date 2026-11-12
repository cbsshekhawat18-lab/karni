"""What the shop's tests share: the test payment provider, products and a checkout."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from karni.testing.factories import create
from karni_payments.providers.test import TestProvider

from shop.models import Category, Product

ADDRESS = {
    "name": "Mira Okafor",
    "line1": "12 Harbour Road",
    "city": "Lisbon",
    "postcode": "1100-148",
    "country": "PT",
}


@pytest.fixture(autouse=True)
def _test_payments(settings: Any) -> None:
    settings.KARNI_PAYMENTS_PROVIDER = "test"
    settings.KARNI_FRONTEND_URL = "https://shop.example.com"
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    TestProvider.reset()


@pytest.fixture
def make_product(db: None) -> Callable[..., Product]:
    def make(**values: Any) -> Product:
        values = {
            "price": Decimal("10.00"),
            "sale_price": None,
            "sale_starts": None,
            "sale_ends": None,
            "stock": 5,
            "reserved": 0,
            "active": True,
            **values,
        }
        product = create(Product, **values)
        product.categories.set([create(Category, parent=None)])
        return product

    return make


def put(client: Any, product: Product, quantity: int, token: str | None = None) -> Any:
    """Set ``quantity`` of ``product`` in the cart ``client`` holds (or ``token`` names)."""
    headers = {"HTTP_X_CART_TOKEN": token} if token else {}
    return client.post(
        "/api/carts/current/items/",
        {"product": str(product.pk), "quantity": quantity},
        format="json",
        **headers,
    )


def checkout(client: Any, token: str | None = None, **body: Any) -> Any:
    headers = {"HTTP_X_CART_TOKEN": token} if token else {}
    data = {"email": "guest@example.com", "billing": ADDRESS, **body}
    return client.post("/api/carts/current/checkout/", data, format="json", **headers)
