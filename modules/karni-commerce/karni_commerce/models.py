"""The cart, the order and how its payments and refunds link to it.

A cart line and an order line name what they sell by ``kind`` (a registered
:class:`~karni_commerce.sellables.Sellable`) and ``item`` (that kind's key,
as text), never by a foreign key: commerce does not know the selling app's
models, and an order line keeps its copied name, SKU and prices when the
item is gone.

An order's ``status`` is its money state only: ``pending`` (waiting for its
payment), ``paid``, ``part_paid``, ``failed``, ``cancelled``, ``refunded``
and ``part_refunded``. What happens to the goods (shipped, checked in,
enrolled) is the selling app's own record.

Override / escape hatch: these are plain :class:`karni.models.BaseModel`
models, extended by your own tables that point at them (a shipment, an
invoice). ``APIMeta`` keeps the money fields read-only in the API: only
:mod:`karni_commerce.services` writes them.
"""

from __future__ import annotations

import secrets
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import models
from django.db.models import Q
from karni.fields import CurrencyField, LiveUniqueConstraint, MoneyField, StateField
from karni.models import BaseModel

__all__ = [
    "ZERO",
    "Cart",
    "CartLine",
    "Order",
    "OrderLine",
    "OrderNote",
    "OrderPayment",
    "OrderRefund",
    "new_key",
]

ZERO = Decimal("0.00")


def new_key() -> str:
    """A secret that lets a visitor reach their own cart or order, and nothing else."""
    return secrets.token_urlsafe(24)


class Cart(BaseModel):
    """A cart: a signed-in person's, or a visitor's, found by its token."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="commerce_carts",
    )
    token = models.CharField(max_length=64, default=new_key)

    class Meta:
        constraints = [LiveUniqueConstraint(fields=["token"], name="karni_commerce_cart_token")]

    class APIMeta:
        exclude = ["token"]
        read_only = ["user"]

    class AdminMeta:
        list_display = ["user", "created_at", "updated_at"]

    class Karni:
        owner_field = "user"

    def __str__(self) -> str:
        return f"Cart {str(self.pk)[:8]}"


class CartLine(BaseModel):
    """One thing in a cart: its kind, its item, the options picked and how many."""

    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="lines")
    kind = models.CharField(max_length=40)
    item = models.CharField(max_length=64)
    options = models.JSONField(default=dict, blank=True)
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            LiveUniqueConstraint(
                fields=["cart", "kind", "item"], name="karni_commerce_cartline_unique"
            ),
            models.CheckConstraint(
                condition=Q(quantity__gte=1), name="karni_commerce_cartline_quantity_gte_1"
            ),
        ]

    class APIMeta:
        read_only = ["cart", "kind", "item", "options", "quantity"]

    class Karni:
        owner_field = "cart__user"
        cascade = {"cart": "a line is part of its cart and goes with it"}

    def __str__(self) -> str:
        return f"{self.quantity} x {self.kind}:{self.item}"


class Order(BaseModel):
    """An order: who bought, what (its lines), for how much, and where the money stands."""

    STATES = (
        "pending",
        "paid",
        "part_paid",
        "failed",
        "cancelled",
        "refunded",
        "part_refunded",
    )

    number = models.PositiveIntegerField()
    # The number as text, for search (karni.global_search takes text fields only).
    reference = models.CharField(max_length=40, blank=True, default="")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="commerce_orders",
    )
    email = models.EmailField()
    buyer_name = models.CharField(max_length=200, blank=True, default="")
    status = StateField(
        states=list(STATES),
        transitions={
            "pending": ["paid", "part_paid", "failed", "cancelled"],
            "part_paid": ["paid", "part_refunded", "refunded"],
            "failed": ["pending", "cancelled"],
            "paid": ["part_refunded", "refunded", "cancelled"],
            "part_refunded": ["refunded"],
        },
    )
    currency = CurrencyField()
    subtotal = MoneyField(currency_field="currency", default=ZERO)
    total = MoneyField(currency_field="currency", default=ZERO)
    amount_paid = MoneyField(currency_field="currency", default=ZERO)
    amount_refunded = MoneyField(currency_field="currency", default=ZERO)
    billing = models.JSONField(default=dict, blank=True)
    shipping = models.JSONField(default=dict, blank=True)
    needs_shipping = models.BooleanField(default=False)
    note = models.TextField(blank=True, default="")
    key = models.CharField(max_length=64, default=new_key)
    hold_until = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            LiveUniqueConstraint(fields=["number"], name="karni_commerce_order_number"),
        ]
        indexes = [
            models.Index(fields=["status", "hold_until"], name="karni_commerce_order_hold"),
            models.Index(fields=["email"], name="karni_commerce_order_email"),
            # revenue by day (the dashboard's tiles and chart)
            models.Index(fields=["paid_at"], name="karni_commerce_order_paid_at"),
        ]

    class APIMeta:
        # The server writes every one of these: checkout, the settlement and refunds.
        read_only = [
            "number",
            "reference",
            "user",
            "email",
            "buyer_name",
            "status",
            "currency",
            "subtotal",
            "total",
            "amount_paid",
            "amount_refunded",
            "billing",
            "shipping",
            "needs_shipping",
            "hold_until",
            "paid_at",
            "cancelled_at",
        ]
        exclude = ["key"]

    class AdminMeta:
        list_display = ["number", "email", "status", "total", "currency", "created_at"]
        search_fields = ["number", "email", "buyer_name"]
        read_only = ["number", "key", "amount_paid", "amount_refunded"]

    class Karni:
        owner_field = "user"
        # A shipment's order column, or any relation to an order, shows its number.
        label = "number"
        # The order page's history: every move of the money (GET orders/{id}/history/).
        audit = ["status", "amount_paid", "amount_refunded"]
        # The staff home's tile (docs/api.md, "The staff dashboard"): the orders by
        # money state, those placed today, and the newest.
        dashboard = {
            "label": "Orders",
            "order": 1,
            "by": "status",
            "values": ["pending", "paid", "failed", "refunded"],
            "counts": {"Placed today": {"created_at__gte": "today"}},
            "recent": 8,
            "columns": ["number", "email", "status", "total", "created_at"],
        }
        search = {
            "fields": ["reference", "email", "buyer_name"],
            "title": "reference",
            "subtitle": "email",
        }

    def __str__(self) -> str:
        return f"Order {self.number}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.number and not self.reference:
            self.reference = str(self.number)
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = {*kwargs["update_fields"], "reference"}
        super().save(*args, **kwargs)

    @property
    def balance(self) -> Decimal:
        """What is still to pay: the total less what was paid."""
        return max(Decimal(self.total) - Decimal(self.amount_paid), ZERO)

    @property
    def refundable(self) -> Decimal:
        """What may still go back: what was paid less what was refunded."""
        return max(Decimal(self.amount_paid) - Decimal(self.amount_refunded), ZERO)

    def guest_may_read(self, key: str) -> bool:
        """Whether ``key`` is this order's secret (a guest reads their order with it)."""
        return bool(key) and secrets.compare_digest(str(key), str(self.key))


class OrderLine(BaseModel):
    """A line of an order, with the item's name, SKU and price as they were at checkout."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    kind = models.CharField(max_length=40)
    item = models.CharField(max_length=64)
    options = models.JSONField(default=dict, blank=True)
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=64, blank=True, default="")
    quantity = models.PositiveIntegerField()
    quantity_refunded = models.PositiveIntegerField(default=0)
    currency = CurrencyField()
    unit_price = MoneyField(currency_field="currency")
    compare_at_price = MoneyField(currency_field="currency", null=True, blank=True)
    line_total = MoneyField(currency_field="currency")
    needs_shipping = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "position"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity_refunded__lte=models.F("quantity")),
                name="karni_commerce_orderline_refunded_lte_quantity",
            ),
        ]
        indexes = [models.Index(fields=["kind", "item"], name="karni_commerce_line_item")]

    class APIMeta:
        read_only = [
            "order",
            "kind",
            "item",
            "options",
            "name",
            "sku",
            "quantity",
            "quantity_refunded",
            "currency",
            "unit_price",
            "compare_at_price",
            "line_total",
            "needs_shipping",
            "position",
        ]

    class Karni:
        owner_field = "order__user"
        cascade = {"order": "a line is part of its order and goes with it"}

    def __str__(self) -> str:
        return f"{self.quantity} x {self.name}"


class OrderPayment(BaseModel):
    """A payment of an order: an order may have several (a retry, a deposit and its balance)."""

    class Purpose(models.TextChoices):
        FULL = "full"
        DEPOSIT = "deposit"
        BALANCE = "balance"
        RETRY = "retry"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="payments")
    payment = models.OneToOneField(
        "karni_payments.Payment", on_delete=models.PROTECT, related_name="commerce_order"
    )
    purpose = models.CharField(max_length=20, choices=Purpose.choices, default=Purpose.FULL)
    currency = CurrencyField()
    amount = MoneyField(currency_field="currency")

    class APIMeta:
        read_only = ["order", "payment", "purpose", "currency", "amount"]

    class Karni:
        owner_field = "order__user"
        cascade = {"order": "the link is part of its order and goes with it"}

    def __str__(self) -> str:
        return f"{self.purpose} payment of order {self.order_id}"


class OrderRefund(BaseModel):
    """A refund of an order: how much, of which lines, and whether the items go back."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="refunds")
    refund = models.OneToOneField(
        "karni_payments.Refund", on_delete=models.PROTECT, related_name="commerce_order"
    )
    currency = CurrencyField()
    amount = MoneyField(currency_field="currency")
    lines = models.JSONField(default=dict, blank=True)
    restock = models.BooleanField(default=False)
    reason = models.CharField(max_length=255, blank=True, default="")
    settled_at = models.DateTimeField(null=True, blank=True)

    class APIMeta:
        read_only = [
            "order",
            "refund",
            "currency",
            "amount",
            "lines",
            "restock",
            "reason",
            "settled_at",
        ]

    class Karni:
        owner_field = "order__user"
        cascade = {"order": "a refund record is part of its order and goes with it"}

    def __str__(self) -> str:
        return f"refund {self.amount} of order {self.order_id}"

    def line_quantities(self) -> dict[str, int]:
        """``{order line id: quantity}`` this refund covers."""
        found: dict[str, Any] = dict(self.lines or {})
        return {str(key): int(value) for key, value in found.items()}


class OrderNote(BaseModel):
    """A note on an order: for the staff only, or for the buyer (who gets it by email too)."""

    class Kind(models.TextChoices):
        INTERNAL = "internal", "Internal"
        CUSTOMER = "customer", "To the customer"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="notes")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.INTERNAL)
    body = models.TextField()
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="commerce_order_notes",
    )

    class Meta:
        ordering = ["created_at"]

    class APIMeta:
        read_only = ["order", "kind", "body", "author"]

    class Karni:
        cascade = {"order": "a note is part of its order and goes with it"}

    def __str__(self) -> str:
        return f"{self.get_kind_display()} note on order {self.order_id}"
