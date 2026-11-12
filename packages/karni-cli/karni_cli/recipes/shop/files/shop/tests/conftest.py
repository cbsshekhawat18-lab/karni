"""What the shop's tests share: the test payment provider, products and a checkout."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from karni.testing.factories import create
from karni_commerce import services as commerce
from karni_commerce.models import Cart, Order
from karni_payments.providers.test import TestProvider
from karni_payments.test_checkout import settle

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
    settings.KARNI_PAYMENTS_CHECKOUT_VALIDATOR = (
        "karni_commerce.payments.checkout_validator"
    )
    settings.KARNI_FRONTEND_URL = "https://shop.example.com"
    settings.KARNI_COMMERCE_STAFF_EMAILS = ["orders@example.com"]
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
    body = {"kind": "product", "item": str(product.pk), "quantity": quantity}
    return client.post("/api/carts/current/lines/", body, format="json", **headers)


def checkout(client: Any, token: str | None = None, **body: Any) -> Any:
    headers = {"HTTP_X_CART_TOKEN": token} if token else {}
    data = {"email": "guest@example.com", "billing": ADDRESS, **body}
    return client.post("/api/carts/current/checkout/", data, format="json", **headers)


def cart_with(*lines: tuple[Product, int]) -> Cart:
    cart = Cart.objects.create()
    for product, quantity in lines:
        commerce.set_line(cart, "product", str(product.pk), quantity)
    return cart


def place(cart: Cart, email: str = "guest@example.com", user: Any = None) -> Order:
    return commerce.checkout(
        cart, user=user, email=email, billing=ADDRESS, shipping=ADDRESS
    )


def pay(order: Order, outcome: str = "pay") -> Order:
    """Start the order's payment and settle it on the test provider's page."""
    commerce.open_payment(order)
    link = order.payments.order_by("-created_at").first()
    assert link is not None
    settle(link.payment, outcome)
    order.refresh_from_db()
    return order
