"""Experimental. The checkout validator that checks an order's payment against the order.

karni-payments calls ``KARNI_PAYMENTS_CHECKOUT_VALIDATOR`` before it creates
any payment. Set it to :func:`checkout_validator`::

    KARNI_PAYMENTS_CHECKOUT_VALIDATOR = "karni_commerce.payments.checkout_validator"

(``modules: {payments: {checkout_validator: karni_commerce.payments.checkout_validator}}``
in karni.yaml). A payment for an order (its metadata names
``commerce_order``) must ask for exactly what the order still owes, in the
order's currency. Every other payment goes to
``KARNI_COMMERCE_OTHER_CHECKOUT_VALIDATOR``.

Commerce links a payment to an order only when it opened the payment itself
(:func:`karni_commerce.services.open_payment`), so a payment made elsewhere
never settles an order. This check refuses a wrong amount before the
provider is called at all.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.utils.module_loading import import_string
from rest_framework.exceptions import ValidationError

from karni_commerce import conf
from karni_commerce.models import Order

__all__ = ["checkout_validator"]


def checkout_validator(
    *, user: Any, amount: Decimal, currency: str, metadata: dict[str, Any]
) -> None:
    """Refuse a payment for an order that asks for anything but what the order owes."""
    key = metadata.get("commerce_order")
    if key is None:
        other = import_string(str(conf.get("KARNI_COMMERCE_OTHER_CHECKOUT_VALIDATOR")))
        other(user=user, amount=amount, currency=currency, metadata=metadata)
        return
    order = Order.objects.filter(pk=key).first()
    if order is None:
        raise ValidationError({"amount": ["No such order."]})
    if Decimal(amount) != order.balance or currency.upper() != order.currency.upper():
        raise ValidationError(
            {"amount": [f"Order {order.number} owes {order.balance:.2f} {order.currency}."]}
        )
