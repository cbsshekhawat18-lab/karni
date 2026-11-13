"""shop models. Each class extends the one karni build writes in shop/karni/models.py
from karni.yaml: add your methods here.

The shop's own rules live here and in shop/services.py: a product's price today and
how many are left, a variation's price and stock, a review's rating, and a shipment's
moves. The cart, the orders, coupons, shipping and tax are karni-commerce's: the shop
sells through it with the adapter in shop/sellables.py.
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
    shelf, and a cancelled or unpaid order gives it back. ``low_stock`` is the level
    at which staff are told it runs low (blank: ``SHOP_LOW_STOCK``), and with
    ``backorders`` it may be ordered past what is left (shop/sellables.py).
    """

    class Meta(karni.Product.Meta):
        constraints = [
            LiveUniqueConstraint(fields=["sku"], name="shop_product_sku_unique"),
            models.CheckConstraint(
                condition=Q(stock__gte=0), name="shop_product_stock_gte_0"
            ),
        ]

    def low_stock_level(self) -> int:
        """The level at which the product runs low: its own, else SHOP_LOW_STOCK."""
        from shop.services import low_stock_level

        return self.low_stock if self.low_stock is not None else low_stock_level()

    def runs_low(self) -> bool:
        return self.active and self.available <= self.low_stock_level()

    def more_description(self) -> str:
        """The description without what the short description already says.

        A product page shows the short description at the top and this below it: the
        whole description when it says something else, the rest of it when it starts
        with the short description, and nothing when the two are the same.
        """
        short = (self.short_description or "").strip()
        full = (self.description or "").strip()
        if short and full.startswith(short):
            return full[len(short) :].strip()
        return full

    def count_ratings(self) -> None:
        """Count the approved reviews again: ``rating_average`` and ``rating_count``."""
        from django.db.models import Avg, Count

        found = Review.objects.filter(product=self, status="approved").aggregate(
            average=Avg("rating"), count=Count("pk")
        )
        average = found["average"]
        Product.objects.filter(pk=self.pk).update(
            rating_average=(
                Decimal(str(average)).quantize(CENT) if average is not None else None
            ),
            rating_count=found["count"] or 0,
        )

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


class Attribute(karni.Attribute):
    """An option products come in: Size, Colour."""

    def __str__(self) -> str:
        return self.name


class AttributeValue(karni.AttributeValue):
    """One value of an attribute: M of Size, Sage of Colour."""

    def __str__(self) -> str:
        return (
            f"{self.attribute.name}: {self.value}" if self.attribute_id else self.value
        )


class Variation(karni.Variation):
    """One way a product is sold: its values (M, Sage), SKU, price, stock and picture.

    A blank ``price`` is the product's price, and a ``sale_price`` runs in the
    product's sale window. ``stock`` and ``available`` work as a product's do: checkout
    holds ``available`` and the payment takes ``stock``. A product with active
    variations is bought by one of them (shop/sellables.py).
    """

    class Meta(karni.Variation.Meta):
        constraints = [
            LiveUniqueConstraint(fields=["sku"], name="shop_variation_sku_unique"),
            models.CheckConstraint(
                condition=Q(stock__gte=0), name="shop_variation_stock_gte_0"
            ),
        ]

    def __str__(self) -> str:
        label = self.label()
        return f"{self.product.name}, {label}" if label else self.product.name

    def ordered_values(self) -> list[AttributeValue]:
        rows = list(self.values.all())
        return sorted(
            rows,
            key=lambda row: (row.attribute.position, row.attribute.name, row.position),
        )

    def label(self) -> str:
        """Its values in words: "M, Sage"."""
        return ", ".join(value.value for value in self.ordered_values())

    def details(self) -> list[dict[str, str]]:
        """Its values as a cart line shows them: [{"label": "Size", "value": "M"}]."""
        return [
            {"label": value.attribute.name, "value": value.value}
            for value in self.ordered_values()
        ]

    def regular_price(self) -> Decimal:
        price = self.price if self.price is not None else self.product.price
        return Decimal(price).quantize(CENT)

    def on_sale(self, at: datetime | None = None) -> bool:
        if self.sale_price is None and self.price is None:
            return self.product.on_sale(at)
        moment = at or timezone.now()
        product = self.product
        return (
            self.sale_price is not None
            and (product.sale_starts is None or product.sale_starts <= moment)
            and (product.sale_ends is None or product.sale_ends > moment)
        )

    def current_price(self, at: datetime | None = None) -> Decimal:
        """What a customer pays for it now."""
        if self.sale_price is None and self.price is None:
            return self.product.current_price(at)
        if self.on_sale(at) and self.sale_price is not None:
            return Decimal(self.sale_price).quantize(CENT)
        return self.regular_price()

    def runs_low(self) -> bool:
        return self.active and self.available <= self.product.low_stock_level()


class Review(karni.Review):
    """A buyer's rating (1 to 5) and words on a product they received.

    A review waits for staff (``pending``) unless ``SHOP_REVIEWS_NEED_APPROVAL`` is
    off. Only approved reviews show, and the product's ``rating_average`` and
    ``rating_count`` count them.
    """

    class Meta(karni.Review.Meta):
        constraints = [
            LiveUniqueConstraint(
                fields=["product", "author"], name="shop_review_one_per_person"
            ),
            models.CheckConstraint(
                condition=Q(rating__gte=1) & Q(rating__lte=5),
                name="shop_review_rating_1_to_5",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.rating} stars for {self.product.name}" if self.product_id else ""

    def save(self, *args: Any, **kwargs: Any) -> None:
        super().save(*args, **kwargs)
        self.product.count_ratings()


class WishlistItem(karni.WishlistItem):
    """A product a customer keeps for later (one row per product)."""

    class Meta(karni.WishlistItem.Meta):
        constraints = [
            LiveUniqueConstraint(fields=["user", "product"], name="shop_wishlist_once"),
        ]


class Shipment(karni.Shipment):
    """The parcel of an order's products: processing, shipped with tracking, delivered.

    The order (karni-commerce) holds the money. The shipment holds what happens to
    the goods. A paid order with products gets one (shop/listeners.py).
    """

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
