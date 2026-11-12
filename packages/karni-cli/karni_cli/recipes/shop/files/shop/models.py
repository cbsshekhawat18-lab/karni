"""shop models. Each class extends the one karni build writes in shop/karni/models.py
from karni.yaml: add your methods here.

The shop's own rules live here and in shop/services.py: a product's price today and
how many are left, and a shipment's moves. The cart, the orders and the payments are
karni-commerce's: the shop sells through it with the adapter in shop/sellables.py.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from django.db import models
from django.db.models import Q
from django.utils import timezone
from karni.fields import LiveUniqueConstraint
from rest_framework.exceptions import ValidationError
from shop.karni import models as karni

CENT = Decimal("0.01")


class Category(karni.Category):
    """A product group. Categories nest: Kitchen holds Cookware and Tableware."""


class Tag(karni.Tag):
    """A label a product can carry besides its categories (gift, handmade)."""


class Product(karni.Product):
    """Something for sale: its price today and how many are left to sell.

    ``stock`` is what is on the shelf. ``available`` is what no order holds of it:
    checkout holds a line (karni.capacity.reserve), the payment takes it off the
    shelf, and a cancelled or unpaid order gives it back.
    """

    class Meta(karni.Product.Meta):
        constraints = [
            LiveUniqueConstraint(fields=["sku"], name="shop_product_sku_unique"),
            models.CheckConstraint(
                condition=Q(stock__gte=0), name="shop_product_stock_gte_0"
            ),
        ]

    class Karni(karni.Product.Karni):
        # The staff home's stock tile (docs/api.md, "The staff dashboard").
        dashboard = {
            "label": "Stock",
            "order": 3,
            "total": False,
            "new_days": 0,
            "counts": {
                "Sold out": {"available__lte": 0, "active": True},
                "Low (3 or fewer)": {"available__lte": 3, "active": True},
            },
            "recent": 0,
        }
        search = {"fields": ["name", "sku"], "title": "name", "subtitle": "sku"}

    def on_sale(self, at: datetime | None = None) -> bool:
        moment = at or timezone.now()
        return (
            self.sale_price is not None
            and (self.sale_starts is None or self.sale_starts <= moment)
            and (self.sale_ends is None or self.sale_ends > moment)
        )

    def current_price(self, at: datetime | None = None) -> Decimal:
        """The price a customer pays now: the sale price while the sale runs."""
        if self.on_sale(at) and self.sale_price is not None:
            return Decimal(self.sale_price).quantize(CENT)
        return Decimal(self.price).quantize(CENT)


class ProductImage(karni.ProductImage):
    """One more picture of a product. The product's own image is its main one."""


class Shipment(karni.Shipment):
    """The parcel of an order's products: processing, shipped with tracking, delivered.

    The order (karni-commerce) holds the money. The shipment holds what happens to
    the goods. A paid order with products gets one (shop/listeners.py).
    """

    class Karni(karni.Shipment.Karni):
        # The staff home's tile: what waits to be sent, and what is on its way.
        dashboard = {
            "label": "Shipments",
            "order": 2,
            "by": "status",
            "values": ["processing", "shipped"],
            "recent": 6,
            "columns": ["order", "status", "tracking_number", "created_at"],
        }

    def __str__(self) -> str:
        return f"Parcel of order {self.order.number}" if self.order_id else "Parcel"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Shipping needs a tracking number, and each move stamps its time."""
        if self.status == "shipped" and not self.tracking_number:
            raise ValidationError(
                {"tracking_number": ["Add the tracking number to mark it shipped."]}
            )
        stamps = {"shipped": "shipped_at", "delivered": "delivered_at"}
        stamp = stamps.get(str(self.status))
        if stamp and getattr(self, stamp) is None:
            setattr(self, stamp, timezone.now())
            fields = kwargs.get("update_fields")
            if fields is not None:
                kwargs["update_fields"] = {*fields, stamp}
        super().save(*args, **kwargs)
