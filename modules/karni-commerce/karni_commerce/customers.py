"""Experimental. The staff's customers: who bought, how often and for how much.

Commerce knows its buyers by the orders: an email, a name, and the account
when the order has one. :class:`OrderCustomers` (the default) groups the
orders a member of staff may read by the buyer's email, in one query:

* :meth:`~OrderCustomers.customers`: one row per buyer, with how many orders,
  what they spent (paid less refunded), and their first and last order.
* :meth:`~OrderCustomers.customer`: one buyer's orders, totals, the
  addresses they gave and their account.

``GET /api/orders/customers/`` and ``GET /api/orders/customer/?email=`` answer
them (:mod:`karni_commerce.viewsets`).

This is a seam. The family's people contract (``karni.people``: a Person,
their addresses and the facts each part contributes) replaces it with a
class of the same two methods, named in ``KARNI_COMMERCE_CUSTOMERS``, and
the screens keep working.

Override / escape hatch: ``KARNI_COMMERCE_CUSTOMERS`` names your own class
(a dotted path), for a CRM or a customer table of your own.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, ClassVar

from django.db.models import Case, Count, F, IntegerField, Max, Min, Q, QuerySet, Sum, When
from django.db.models.functions import Coalesce, Lower
from django.utils.module_loading import import_string

from karni_commerce import conf
from karni_commerce.models import ZERO, Order

__all__ = ["CustomerPage", "OrderCustomers", "customers_backend"]

_MONEY = Sum(F("amount_paid") - F("amount_refunded"))


@dataclass(frozen=True)
class CustomerPage:
    """One buyer: who they are, what they spent, their orders and addresses."""

    email: str
    name: str
    orders: list[Order]
    order_count: int
    spent: Decimal
    currency: str
    first_order: Any
    last_order: Any
    addresses: list[dict[str, Any]]
    account: Any


class OrderCustomers:
    """Experimental. The buyers of the orders, one per email (the default backend)."""

    #: What the list may be sorted by (``-`` first for the other way).
    ORDERINGS: ClassVar[dict[str, str]] = {
        "last_order": "last_order",
        "first_order": "first_order",
        "orders": "order_count",
        "spent": "spent",
        "email": "email",
        "name": "name",
    }

    def customers(
        self, orders: QuerySet[Order], *, search: str = "", ordering: str = "-last_order"
    ) -> QuerySet[Any]:
        """One row per buyer of ``orders``: ``email``, ``name``, ``has_account``,
        ``order_count``, ``spent``, ``first_order`` and ``last_order``. One query."""
        if search.strip():
            text = search.strip()
            orders = orders.filter(
                Q(email__icontains=text) | Q(buyer_name__icontains=text) | Q(reference=text)
            )
        rows = (
            orders.order_by()
            .annotate(buyer_key=Lower("email"))
            .values("buyer_key")
            .annotate(
                email=Max("email"),
                name=Max("buyer_name"),
                has_account=Max(
                    Case(When(user__isnull=False, then=1), default=0, output_field=IntegerField())
                ),
                order_count=Count("id"),
                spent=Coalesce(_MONEY, ZERO),
                first_order=Min("created_at"),
                last_order=Max("created_at"),
            )
        )
        descending = ordering.startswith("-")
        field = self.ORDERINGS.get(ordering.lstrip("-"), "last_order")
        return rows.order_by(f"-{field}" if descending else field, "buyer_key")

    def customer(self, orders: QuerySet[Order], email: str) -> CustomerPage | None:
        """The buyer of ``email`` among ``orders``, or ``None`` when none of them is theirs."""
        found = orders.filter(email__iexact=email.strip()).select_related("user")
        mine = list(found.order_by("-created_at"))
        if not mine:
            return None
        spent = sum(
            (Decimal(order.amount_paid) - Decimal(order.amount_refunded) for order in mine), ZERO
        )
        addresses: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        for order in mine:
            for address in (order.shipping, order.billing):
                if not address:
                    continue
                key = tuple(sorted((k, str(v)) for k, v in dict(address).items()))
                if key not in seen:
                    seen.add(key)
                    addresses.append(dict(address))
        account = next((order.user for order in mine if order.user_id), None)
        named = next((order.buyer_name for order in mine if order.buyer_name), "")
        return CustomerPage(
            email=mine[0].email,
            name=named,
            orders=mine,
            order_count=len(mine),
            spent=spent,
            currency=mine[0].currency or conf.currency(),
            first_order=mine[-1].created_at,
            last_order=mine[0].created_at,
            addresses=addresses,
            account=account,
        )


def customers_backend() -> Any:
    """Experimental. The customers backend ``KARNI_COMMERCE_CUSTOMERS`` names (an instance)."""
    path = str(conf.get("KARNI_COMMERCE_CUSTOMERS") or "")
    found = import_string(path) if path else OrderCustomers
    return found() if isinstance(found, type) else found
