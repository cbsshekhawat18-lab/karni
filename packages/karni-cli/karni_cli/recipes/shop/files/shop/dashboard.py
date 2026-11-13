"""The shop's home tiles (karni.tiles): what runs low, and what sells best.

The counts that are a filter of a list (orders to fulfil, sold out) are declared in
karni.yaml's ``dashboard:``. These two need the server: each product's own low-stock
level, and the quantities sold in 30 days. karni-commerce adds the revenue tiles.

Change a tile here, or place it (order, size, who sees it) in karni.yaml's
``dashboard:`` by its key, or hide it there with ``hidden: true``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db.models import F, IntegerField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from karni.tiles import register
from karni_commerce.models import OrderLine

from shop.models import Product
from shop.services import low_stock_level

PAID = ("paid", "part_paid", "part_refunded")


@register(
    key="shop.low_stock",
    title="Running low",
    kind="list",
    requires="shop.product:change",
    order=20,
    size="half",
    link="/products?ordering=available",
)
def low_stock(request: Any) -> dict[str, Any]:
    """Active products at or under their low-stock level, the fewest left first."""
    level = Coalesce(
        F("low_stock"), Value(low_stock_level()), output_field=IntegerField()
    )
    rows = (
        Product.objects.filter(active=True)
        .annotate(level=level)
        .filter(available__lte=F("level"))
        .order_by("available", "name")[:8]
    )
    return {
        "columns": [
            {"key": "name", "label": "Product", "format": "text"},
            {"key": "sku", "label": "SKU", "format": "text"},
            {"key": "available", "label": "Left", "format": "number"},
        ],
        "rows": [
            {
                "name": product.name,
                "sku": product.sku,
                "available": product.available,
                "link": f"/products/{product.slug}",
            }
            for product in rows
        ],
    }


@register(
    key="shop.top_products",
    title="Best sellers, 30 days",
    kind="list",
    requires="karni_commerce.order:view",
    order=21,
    size="half",
)
def top_products(request: Any) -> dict[str, Any]:
    """The products sold most in paid orders of the last 30 days, less refunds."""
    since = timezone.now() - timedelta(days=30)
    sold = (
        OrderLine.objects.filter(
            Q(order__status__in=PAID), kind="product", order__paid_at__gte=since
        )
        .values("item", "name")
        .annotate(sold=Sum(F("quantity") - F("quantity_refunded")))
        .order_by("-sold", "name")[:5]
    )
    slugs = dict(
        Product.objects.filter(pk__in=[row["item"] for row in sold]).values_list(
            "pk", "slug"
        )
    )
    rows = []
    for row in sold:
        slug = slugs.get(_key(row["item"]))
        rows.append(
            {
                "name": row["name"],
                "sold": row["sold"],
                "link": f"/products/{slug}" if slug else None,
            }
        )
    return {
        "columns": [
            {"key": "name", "label": "Product", "format": "text"},
            {"key": "sold", "label": "Sold", "format": "number"},
        ],
        "rows": rows,
    }


def _key(value: str) -> Any:
    """An order line's item as the product's primary key."""
    field = Product._meta.pk
    return field.to_python(value) if field is not None else value
