"""What commerce tells the people contract about a person: their orders.

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

The staff's customers are the people who bought, with these facts:
:func:`customers` (``GET /api/orders/customers/``) and :func:`customer`
(``GET /api/orders/customer/?email=`` or ``?person=``), both over the orders
the caller may read.

Override / escape hatch: ``people.register_fact(name, ..., replace=True)``
swaps a fact, ``people.unregister_fact(name)`` removes one. A project that
keeps its customers elsewhere overrides the two viewset actions.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, ClassVar

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from django.db.models import Exists, F, Min, OuterRef, Q, QuerySet, Subquery, Sum
from django.db.models.functions import Coalesce
from karni import people
from karni.people.models import Person, normalize_email

from karni_commerce import conf
from karni_commerce.models import ZERO, Order

__all__ = [
    "FACTS",
    "ORDERINGS",
    "CustomerPage",
    "customer",
    "customers",
    "first_order",
    "total_spent",
]

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


# -- the staff's customers: the people who bought ------------------------------------------

#: What the customers list may be sorted by (``-`` first for the other way), and the
#: fact or field behind each.
ORDERINGS: dict[str, str] = {
    "last_order": "last_order",
    "first_order": "first_order",
    "orders": "orders",
    "spent": "total_spent",
    "email": "email",
    "name": "display_name",
}


def customers(
    orders: QuerySet[Order], *, search: str = "", ordering: str = "-last_order"
) -> QuerySet[Person]:
    """The people with an order among ``orders``, with commerce's facts, in one query.

    Each row is a :class:`~karni.people.models.Person` with ``orders``,
    ``total_spent``, ``last_order``, ``first_order`` and ``has_account`` (an
    account linked to the person, or an order placed while signed in).
    ``search`` finds a name, an email or an order number.
    """
    theirs = orders.filter(person=OuterRef("pk"))
    rows = Person.objects.filter(Exists(theirs)).with_facts(*FACTS)
    rows = rows.annotate(
        has_account=Q(user__isnull=False) | Exists(theirs.filter(user__isnull=False))
    )
    text = search.strip()
    if text:
        rows = rows.filter(
            Q(display_name__icontains=text)
            | Q(email__icontains=text)
            | Exists(theirs.filter(Q(reference=text) | Q(buyer_name__icontains=text)))
        )
    descending = ordering.startswith("-")
    field = ORDERINGS.get(ordering.lstrip("-"), "last_order")
    first = F(field).desc(nulls_last=True) if descending else F(field).asc(nulls_last=True)
    return rows.order_by(first, "email", "pk")


@dataclass(frozen=True)
class CustomerPage:
    """One customer: the person, what they spent, their orders and addresses."""

    person: Person
    orders: list[Order]
    order_count: int
    spent: Decimal
    currency: str
    first_order: Any
    last_order: Any
    addresses: list[dict[str, Any]]
    account: Any

    ADDRESS_FIELDS: ClassVar[tuple[str, ...]] = (
        "line1",
        "line2",
        "city",
        "region",
        "postcode",
        "country",
    )


def _saved_addresses(person: Person) -> list[dict[str, Any]]:
    from karni.people.models import Address

    found = []
    for row in Address.objects.filter(person=person).order_by("-is_default_shipping", "label"):
        found.append(
            {
                "name": person.display_name,
                "label": row.label,
                **{name: str(getattr(row, name) or "") for name in CustomerPage.ADDRESS_FIELDS},
            }
        )
    return found


def customer(
    orders: QuerySet[Order], *, email: str = "", person: Any = None
) -> CustomerPage | None:
    """The customer of ``email`` (or the person of id ``person``) among the buyers of
    ``orders``, or ``None`` when none of those orders is theirs."""
    if person:
        try:
            found = Person.objects.filter(pk=person).first()
        except (ValueError, DjangoValidationError):  # not a person's id
            return None
    else:
        address = normalize_email(email)
        found = Person.objects.filter(email=address).first() if address else None
    if found is None:
        return None
    mine = list(orders.filter(person=found).select_related("user").order_by("-created_at"))
    if not mine:
        return None
    facts = Person.objects.with_facts("total_spent").filter(pk=found.pk).first()
    spent = Decimal(getattr(facts, "total_spent", ZERO) or ZERO)
    addresses = _saved_addresses(found)
    seen: set[tuple[Any, ...]] = set()
    for order in mine:
        for address in (order.shipping, order.billing):
            if not address:
                continue
            key = tuple(sorted((k, str(v)) for k, v in dict(address).items()))
            if key not in seen:
                seen.add(key)
                addresses.append(dict(address))
    account = found.user or next((order.user for order in mine if order.user_id), None)
    return CustomerPage(
        person=found,
        orders=mine,
        order_count=len(mine),
        spent=spent,
        currency=mine[0].currency or conf.currency(),
        first_order=mine[-1].created_at,
        last_order=mine[0].created_at,
        addresses=addresses,
        account=account,
    )
