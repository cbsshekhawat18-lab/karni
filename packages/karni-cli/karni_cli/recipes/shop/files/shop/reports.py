"""The shop's reports beside karni-commerce's (sales by date, by item, coupons used).

* ``shop.sales_by_category``: what sold in each category, in the range. A sale counts
  in its category and in each one above it, and the totals count the top ones.
* ``shop.stock``: every product (and variation) with what is left, the low-stock level
  and its state now.

Each answers a table that the Reports page shows and exports to CSV
(``GET /api/orders/reports/<key>/``). Add one here with ``register_report``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db.models import F, Sum
from django.db.models.functions import Coalesce
from karni_commerce.models import ZERO, OrderLine
from karni_commerce.reports import Column, ReportQuery, paid_orders, register_report

from shop.models import Category, Product, Variation
from shop.services import low_stock_level, with_stock


@register_report(
    key="shop.sales_by_category",
    title="Sales by category",
    describe="What sold in each category, top categories first, in the range.",
    order=25,
)
def sales_by_category(query: ReportQuery) -> dict[str, Any]:
    sold = {
        row["item"]: row
        for row in OrderLine.objects.filter(
            order__in=paid_orders(query), kind="product"
        )
        .values("item")
        .annotate(
            quantity=Coalesce(Sum(F("quantity") - F("quantity_refunded")), 0),
            sales=Coalesce(Sum("line_total"), ZERO),
            discounts=Coalesce(Sum("discount"), ZERO),
        )
    }
    categories = {category.pk: category for category in Category.objects.all()}
    totals: dict[Any, dict[str, Any]] = {}
    products = Product.categories.through.objects.filter(
        product_id__in=[key for key in sold]
    ).values_list("product_id", "category_id")
    for product_id, category_id in products:
        row = sold.get(str(product_id))
        node = categories.get(category_id)
        counted: set[Any] = set()
        while row is not None and node is not None and node.pk not in counted:
            counted.add(node.pk)  # a sale counts in its category and each one above
            entry = totals.setdefault(
                node.pk,
                {
                    "category": node.name,
                    "parent": categories[node.parent_id].name
                    if node.parent_id in categories
                    else "",
                    "sold": 0,
                    "sales": Decimal(0),
                    "discounts": Decimal(0),
                },
            )
            entry["sold"] += row["quantity"]
            entry["sales"] += row["sales"]
            entry["discounts"] += row["discounts"]
            node = categories.get(node.parent_id) if node.parent_id else None
    rows = sorted(
        totals.values(), key=lambda entry: (entry["parent"] != "", -entry["sales"])
    )
    for entry in rows:
        entry["net"] = entry["sales"] - entry["discounts"]
    tops = [entry for entry in rows if not entry["parent"]]  # each sale counted once
    totals = {
        key: sum((entry[key] for entry in tops), Decimal(0))
        for key in ("sales", "discounts", "net")
    }
    return {
        "totals": {"sold": sum(entry["sold"] for entry in tops), **totals},
        "columns": [
            Column("category", "Category"),
            Column("parent", "In"),
            Column("sold", "Sold", "number"),
            Column("sales", "Sales", "money"),
            Column("discounts", "Discounts", "money"),
            Column("net", "Net", "money"),
        ],
        "rows": rows,
    }


@register_report(
    key="shop.stock",
    title="Stock",
    describe="Each product and variation: what is left and its low-stock level.",
    dated=False,
    order=40,
)
def stock(query: ReportQuery) -> dict[str, Any]:
    level = low_stock_level()
    rows: list[dict[str, Any]] = []
    variations: dict[Any, list[Variation]] = {}
    for variation in (
        Variation.objects.filter(active=True)
        .prefetch_related("values__attribute")
        .select_related("product")
        .order_by("position", "sku")
    ):
        variations.setdefault(variation.product_id, []).append(variation)
    for product in with_stock(Product.objects.all()).order_by("name"):
        own = product.low_stock if product.low_stock is not None else level
        rows.append(
            _stock_row(
                product.name,
                product.sku,
                product.stock_total,
                product.available_total,
                own,
                product,
            )
        )
        for variation in variations.get(product.pk, []):
            rows.append(
                _stock_row(
                    f"{product.name}, {variation.label()}",
                    variation.sku,
                    variation.stock,
                    variation.available,
                    own,
                    product,
                )
            )
    return {
        "columns": [
            Column("name", "Product"),
            Column("sku", "SKU"),
            Column("state", "State"),
            Column("stock", "On the shelf", "number"),
            Column("held", "Held by orders", "number"),
            Column("available", "Left to sell", "number"),
            Column("level", "Low at", "number"),
            Column("value", "Value at price", "money"),
        ],
        "rows": rows,
    }


def _stock_row(
    name: str, sku: str, on_shelf: int, left: int, level: int, product: Product
) -> dict[str, Any]:
    if not product.active:
        state = "Not for sale"
    elif product.digital:
        state = "Digital"
    elif left <= 0:
        state = "Backorder" if product.backorders else "Sold out"
    elif left <= level:
        state = "Running low"
    else:
        state = "In stock"
    return {
        "name": name,
        "sku": sku,
        "state": state,
        "stock": on_shelf,
        "held": max(on_shelf - left, 0),
        "available": left,
        "level": level,
        "value": Decimal(product.price) * max(on_shelf, 0),
    }
