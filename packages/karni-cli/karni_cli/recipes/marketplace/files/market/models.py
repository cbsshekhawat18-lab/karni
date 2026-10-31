"""market models. Each class extends the one karni build writes in market/karni/models.py
from karni.yaml: add your methods here.
"""

from decimal import Decimal
from typing import Any

from django.conf import settings
from karni.events import on_transition, on_updated
from karni_payments.models import Payment

from market.karni import models as karni

#: The marketplace's share of an order, in percent, unless settings.MARKETPLACE_FEE_PERCENT says.
DEFAULT_FEE_PERCENT = Decimal("10")
CENT = Decimal("0.01")


class Seller(karni.Seller):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class Listing(karni.Listing):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class Order(karni.Order):
    """A buyer's order of a listing. The seller is paid its amount less the fee."""

    class APIMeta:
        read_only = ["amount", "status", "payment"]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self._state.adding:  # the listing's price, never what the buyer sends
            self.amount = self.listing.price * self.quantity
        super().save(*args, **kwargs)

    def fee(self) -> Decimal:
        """The marketplace's share: MARKETPLACE_FEE_PERCENT of the amount, to the cent."""
        percent = Decimal(str(getattr(settings, "MARKETPLACE_FEE_PERCENT", DEFAULT_FEE_PERCENT)))
        return (self.amount * percent / 100).quantize(CENT)

    def payout_amount(self) -> Decimal:
        """What the seller is paid for this order: the amount less the fee."""
        return self.amount - self.fee()


class Payout(karni.Payout):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


@on_transition(Order, "status", to="paid")
def owe_the_seller(order: Order) -> None:
    """A paid order owes its seller the payout."""
    Payout.objects.create(
        seller=order.listing.seller, order=order, amount=order.payout_amount(), fee=order.fee()
    )


@on_updated(Payment)
def mark_the_order_paid(payment: Payment) -> None:
    """The payment provider's webhook settled the payment: its pending order is paid."""
    if payment.status != Payment.Status.SUCCEEDED:
        return
    for order in Order.objects.filter(payment=payment, status="pending"):
        order.transition("status", "paid")
