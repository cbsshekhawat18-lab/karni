"""The marketplace rules: an order's amount, and the payout less the fee."""

from decimal import Decimal
from typing import Any

import pytest
from karni.testing.factories import create
from karni_payments.models import Payment
from karni_payments.providers.test import TestProvider

from market.models import Listing, Order, Payout

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _test_payments(settings: Any) -> None:
    settings.KARNI_PAYMENTS_PROVIDER = "test"
    TestProvider.reset()


def test_a_paid_order_pays_its_seller_less_the_fee(
    client_as: Any, settings: Any
) -> None:
    settings.MARKETPLACE_FEE_PERCENT = 12.5
    listing = create(Listing, price=Decimal("40.00"))
    buyer = client_as("buyer")
    ordered = buyer.post("/api/orders/", {"listing": str(listing.pk), "quantity": 2})
    assert ordered.status_code == 201, ordered.content
    order = Order.objects.get(pk=ordered.json()["id"])
    assert order.amount == Decimal("80.00") and order.buyer == buyer.user
    paid = buyer.post(f"/api/orders/{order.pk}/pay/")
    assert paid.status_code == 200, paid.content
    payment = Payment.objects.get(pk=paid.json()["payment"])
    payment.status = Payment.Status.SUCCEEDED  # what the provider's webhook does
    payment.save()
    payout = Payout.objects.get(order=order)
    assert (payout.seller, payout.amount, payout.fee) == (
        listing.seller,
        Decimal("70.00"),
        Decimal("10.00"),
    )


def test_the_fee_is_ten_percent_unless_the_settings_say() -> None:
    order = create(Order, listing=create(Listing, price=Decimal("19.99")), quantity=1)
    assert (order.fee(), order.payout_amount()) == (Decimal("2.00"), Decimal("17.99"))
