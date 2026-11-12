"""shop models. Each class extends the one karni build writes in shop/karni/models.py
from karni.yaml: add your methods here.

The shop's rules live here and in shop/services.py: a product's price today,
its stock (on hand, and reserved by orders waiting for their payment), the
order number and an order's lines, copied from the cart at checkout.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from karni.fields import LiveUniqueConstraint
from shop.karni import models as karni

ZERO = Decimal("0.00")


def new_key() -> str:
    """A secret that lets a guest read their own order or cart, and nothing else."""
    return secrets.token_urlsafe(24)


class Category(karni.Category):
    """A product group. Categories nest: Kitchen holds Cookware and Tableware."""


class Tag(karni.Tag):
    """A label a product can carry besides its categories (gift, handmade)."""


class Product(karni.Product):
    """Something for sale: its price today and how many are left to sell."""

    # What orders waiting for their payment hold of the stock (shop/services.py).
    reserved = models.IntegerField(default=0)

    class Meta(karni.Product.Meta):
        constraints = [
            LiveUniqueConstraint(fields=["sku"], name="shop_product_sku_unique"),
            models.CheckConstraint(condition=Q(stock__gte=0), name="shop_product_stock_gte_0"),
            models.CheckConstraint(
                condition=Q(reserved__gte=0) & Q(reserved__lte=F("stock")),
                name="shop_product_reserved_in_stock",
            ),
        ]

    class APIMeta:
        # Reservations move only with orders (shop/services.py), never by hand.
        read_only = ["reserved"]

    class Karni(karni.Product.Karni):
        # The back office's dashboard (docs/api.md, "The staff dashboard").
        dashboard = {
            "label": "Stock",
            "order": 2,
            "total": False,
            "new_days": 0,
            "counts": {"Sold out": {"stock__lte": 0}, "Low (3 or fewer)": {"stock__lte": 3}},
            "recent": 0,
        }

    def on_sale(self, at: datetime | None = None) -> bool:
        moment = at or timezone.now()
        return (
            self.sale_price is not None
            and (self.sale_starts is None or self.sale_starts <= moment)
            and (self.sale_ends is None or self.sale_ends > moment)
        )

    def current_price(self, at: datetime | None = None) -> Decimal:
        """The price a customer pays now: the sale price while the sale runs."""
        price = self.sale_price if self.on_sale(at) and self.sale_price is not None else self.price
        return Decimal(price).quantize(Decimal("0.01"))

    @property
    def available(self) -> int:
        """How many a customer can still buy: the stock that no order holds."""
        return max(self.stock - self.reserved, 0)


class ProductImage(karni.ProductImage):
    """One more picture of a product. The product's own image is its main one."""


class Cart(karni.Cart):
    """A cart: a customer's, or a visitor's, found by its token until they sign in."""

    def lines(self) -> list[CartItem]:
        return list(
            self.cartitem_set.select_related("product").order_by("created_at", "product__name")
        )


class CartItem(karni.CartItem):
    """A product and how many of it the cart holds."""


class Address(karni.Address):
    """An address a customer keeps for their next checkout."""

    def as_dict(self) -> dict[str, str]:
        fields = ("name", "company", "line1", "line2", "city", "region", "postcode", "phone")
        found = {name: str(getattr(self, name) or "") for name in fields}
        found["country"] = str(self.country or "")
        return found


class Order(karni.Order):
    """An order: its lines are copied from the cart, and its totals come from them."""

    class Meta(karni.Order.Meta):
        constraints = [LiveUniqueConstraint(fields=["number"], name="shop_order_number_unique")]

    class APIMeta:
        # The server writes these: the number, the money and the times. The guest's key
        # never leaves the server but in checkout's answer.
        read_only = ["number", "subtotal", "total", "payment", "paid_at", "reserved_until"]
        exclude = ["key"]

    class Karni(karni.Order.Karni):
        # The back office's dashboard: what waits for staff, and the newest orders.
        dashboard = {
            "label": "Orders",
            "order": 1,
            "by": "status",
            "values": ["paid", "processing", "shipped"],
            "counts": {"Placed today": {"created_at__gte": "today"}},
            "recent": 8,
            "columns": ["number", "email", "status", "total", "created_at"],
        }

    def save(self, *args: Any, **kwargs: Any) -> None:
        """A new order gets the next number, a guest key and zero totals until it has lines."""
        if self.number is None:
            highest = Order.objects.aggregate(highest=models.Max("number"))["highest"]
            self.number = int(highest or 1000) + 1
        if not self.key:
            self.key = new_key()
        for name in ("subtotal", "total"):
            if getattr(self, name) is None:
                setattr(self, name, ZERO)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Order {self.number}"

    def lines(self) -> list[OrderItem]:
        return list(self.orderitem_set.select_related("product").order_by("created_at", "name"))

    def items_total(self) -> Decimal:
        """The sum of the lines, as the server computes it."""
        return sum((line.line_total for line in self.lines()), ZERO)

    @property
    def payable(self) -> bool:
        """Waiting for its payment, and the stock still held for it."""
        return self.status == "pending" and (
            self.reserved_until is None or self.reserved_until > timezone.now()
        )


class OrderItem(karni.OrderItem):
    """A line of an order, with the product's name and price as they were at checkout."""

    @classmethod
    def from_product(cls, order: Order, product: Product, quantity: int) -> OrderItem:
        price = product.current_price()
        return cls(
            order=order,
            product=product,
            name=product.name,
            sku=product.sku,
            quantity=quantity,
            unit_price=price,
            line_total=(price * quantity).quantize(Decimal("0.01")),
        )
