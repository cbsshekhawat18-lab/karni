"""Experimental. What commerce tells the people contract about a person: their orders.

``karni.people`` imports this module at startup (``<app>/people.py``). The
facts are SQL expressions over :class:`~karni_commerce.models.Order`, so a CRM
segment, the person page and the staff's customers list filter and sort on
them in the database, without knowing commerce:

``orders``
    How many orders the person placed (every live order, whatever its state).
``total_spent``
    What they paid, less what went back to them.
``last_order`` and ``first_order``
    When they placed their latest and their first order.

A person's erase request blanks their name, email, addresses and note on
every order they placed. The amounts, lines and numbers stay, so the books
still add up.

Override / escape hatch: ``people.register_fact(name, ..., replace=True)``
swaps a fact, ``people.unregister_fact(name)`` removes one.
"""

from __future__ import annotations

from typing import Any

from django.db import models
from django.db.models import F, Min, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
from karni import people

from karni_commerce.models import ZERO, Order

__all__ = ["FACTS", "first_order", "total_spent"]

#: The facts commerce registers, by name.
FACTS: tuple[str, ...] = ("orders", "total_spent", "last_order", "first_order")


def _rows() -> models.QuerySet[Order]:
    return Order.objects.filter(person=OuterRef("pk")).order_by().values("person")


def total_spent() -> Any:
    """What the person paid on their orders, less what was refunded (0 for none)."""
    money = models.DecimalField(max_digits=14, decimal_places=2)
    summed = _rows().annotate(total=Sum(F("amount_paid") - F("amount_refunded"))).values("total")
    return Coalesce(Subquery(summed, output_field=money), ZERO, output_field=money)


def first_order() -> Any:
    """When the person placed their first order, or ``None``."""
    first = _rows().annotate(first=Min("created_at")).values("first")
    return Subquery(first, output_field=models.DateTimeField())


people.register_fact(
    "orders",
    people.count_of(Order),
    label="Orders",
    kind="count",
    description="How many orders the person placed.",
    replace=True,
)
people.register_fact(
    "total_spent",
    total_spent,
    label="Total spent",
    kind="money",
    description="What the person paid on their orders, less refunds.",
    replace=True,
)
people.register_fact(
    "last_order",
    people.latest_of(Order, "created_at"),
    label="Last order",
    kind="datetime",
    description="When the person placed their latest order.",
    replace=True,
)
people.register_fact(
    "first_order",
    first_order,
    label="First order",
    kind="datetime",
    description="When the person placed their first order.",
    replace=True,
)

people.erasable(
    Order,
    fields={"buyer_name": "", "email": "", "billing": {}, "shipping": {}, "note": ""},
)
