"""The shop's rules: an order's total is its items', and checkout opens the payment."""

from decimal import Decimal
from typing import Any

import pytest
from karni.testing.factories import create
from karni_payments.models import Payment
from karni_payments.providers.test import TestProvider

from shop.models import Cart, CartItem, Order, OrderItem, Product

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _test_payments(settings: Any) -> None:
    settings.KARNI_PAYMENTS_PROVIDER = "test"
    TestProvider.reset()


def test_an_order_total_is_the_sum_of_its_items() -> None:
    order = create(Order, total=Decimal("0.00"))
    first = create(OrderItem, order=order, quantity=2, unit_price=Decimal("4.50"))
    create(OrderItem, order=order, quantity=1, unit_price=Decimal("10.00"))
    order.refresh_from_db()
    assert order.total == Decimal("19.00")
    first.delete()
    order.refresh_from_db()
    assert order.total == Decimal("10.00")


def test_checkout_makes_the_order_and_opens_its_payment(client_as: Any) -> None:
    client = client_as("customer")
    cart = create(Cart, customer=client.user)
    create(
        CartItem, cart=cart, quantity=3, product=create(Product, price=Decimal("2.00"))
    )
    response = client.post(f"/api/carts/{cart.pk}/checkout/")
    assert response.status_code == 201, response.content
    order = Order.objects.get(pk=response.json()["order"])
    assert order.customer == client.user and order.status == "pending"
    assert order.total == Decimal("6.00") and not cart.cartitem_set.exists()
    payment = Payment.objects.get(pk=response.json()["payment"])
    assert payment.amount == order.total and order.payment == payment
    payment.status = Payment.Status.SUCCEEDED  # what the provider's webhook does
    payment.save()
    order.refresh_from_db()
    assert order.status == "paid"


def test_an_empty_cart_has_nothing_to_check_out(client_as: Any) -> None:
    client = client_as("customer")
    cart = create(Cart, customer=client.user)
    assert client.post(f"/api/carts/{cart.pk}/checkout/").status_code == 400
