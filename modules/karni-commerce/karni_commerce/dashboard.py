"""Commerce's home tiles (:mod:`karni.tiles`): revenue and the latest orders.

Every kind sold through commerce counts: a product, a booking, a course.

* ``commerce.revenue``: what came in today, in the last 7 and the last 30
  days (paid, less what went back), and how many orders were paid.
* ``commerce.revenue_chart``: the same money day by day over 30 days.
* ``commerce.latest_orders``: the newest orders, with their buyer and state.

Each reads the orders its viewer's grants give (``karni_commerce.order:view``).
A project places, retitles or hides them with ``dashboard:`` in karni.yaml.

Override / escape hatch: ``karni.tiles.unregister("commerce.revenue")``, or
``hidden: true`` on the tile in ``dashboard:``.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

from django.db.models import Count, F, Q, QuerySet, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone
from karni.accounts.roles import rows_for
from karni.tiles import Tile, register

from karni_commerce import conf
from karni_commerce.models import ZERO, Order

__all__ = ["latest_orders", "revenue", "revenue_chart"]

NET = Coalesce(Sum(F("amount_paid") - F("amount_refunded")), ZERO)
STATE_WORDS = {
    "pending": "Waiting for payment",
    "paid": "Paid",
    "part_paid": "Part paid",
    "failed": "Payment failed",
    "cancelled": "Cancelled",
    "refunded": "Refunded",
    "part_refunded": "Part refunded",
}


def readable(request: Any) -> QuerySet[Order]:
    """The orders the person of ``request`` may read, by their grants."""
    rows = rows_for(getattr(request, "user", None), Order, "view")
    if rows is True:
        return Order.objects.all()
    if rows is False:
        return Order.objects.none()
    return Order.objects.filter(rows)


def _midnight(days_ago: int) -> datetime:
    day = timezone.localdate() - timedelta(days=days_ago)
    return timezone.make_aware(datetime.combine(day, time.min))


@register(
    key="commerce.revenue",
    title="Revenue",
    requires="karni_commerce.order:view",
    order=10,
    size="full",
    link="/orders?orders.status=paid",
)
def revenue(request: Any) -> dict[str, Any]:
    """Money in today, in 7 and in 30 days, and the orders paid in 30 days."""
    paid = readable(request).filter(paid_at__isnull=False)
    figures = paid.aggregate(
        today=Coalesce(Sum(F("amount_paid") - F("amount_refunded"), filter=_since(0)), ZERO),
        week=Coalesce(Sum(F("amount_paid") - F("amount_refunded"), filter=_since(6)), ZERO),
        month=Coalesce(Sum(F("amount_paid") - F("amount_refunded"), filter=_since(29)), ZERO),
        orders=Count("id", filter=_since(29)),
    )
    return Tile.stat_values(
        [
            ("Today", figures["today"], "money"),
            ("Last 7 days", figures["week"], "money"),
            ("Last 30 days", figures["month"], "money"),
            ("Orders paid in 30 days", figures["orders"], "number"),
        ],
        currency=conf.currency(),
    )


def _since(days_ago: int) -> Q:
    return Q(paid_at__gte=_midnight(days_ago))


@register(
    key="commerce.revenue_chart",
    title="Revenue by day",
    kind="chart",
    requires="karni_commerce.order:view",
    order=11,
    size="full",
)
def revenue_chart(request: Any) -> dict[str, Any]:
    """The money paid each day of the last 30 days (a day with nothing shows 0)."""
    start = _midnight(29)
    rows = (
        readable(request)
        .filter(paid_at__gte=start)
        .annotate(day=TruncDate("paid_at", tzinfo=timezone.get_current_timezone()))
        .values("day")
        .annotate(net=NET)
        .order_by("day")
    )
    by_day = {row["day"]: row["net"] for row in rows}
    today = timezone.localdate()
    points = []
    for offset in range(29, -1, -1):
        day = today - timedelta(days=offset)
        points.append({"label": day.isoformat(), "value": by_day.get(day, ZERO)})
    return {"kind": "bar", "format": "money", "currency": conf.currency(), "points": points}


@register(
    key="commerce.latest_orders",
    title="Latest orders",
    kind="list",
    requires="karni_commerce.order:view",
    order=30,
    size="half",
    link="/orders",
)
def latest_orders(request: Any) -> dict[str, Any]:
    """The 8 newest orders: number, buyer, state and total, each a link to its page."""
    rows = readable(request).select_related("user").order_by("-created_at")[:8]
    path = str(conf.get("KARNI_COMMERCE_ORDER_PATH")).split("?", 1)[0]
    return {
        "columns": [
            {"key": "number", "label": "Order", "format": "text"},
            {"key": "buyer", "label": "Customer", "format": "text"},
            {"key": "status", "label": "Status", "format": "text"},
            {"key": "total", "label": "Total", "format": "money"},
        ],
        "currency": conf.currency(),
        "rows": [
            {
                "number": str(order.number),
                "buyer": order.buyer_name or order.email,
                "status": STATE_WORDS.get(order.status, order.status),
                "total": order.total,
                "link": path.format(number=order.number, key=""),
            }
            for order in rows
        ],
    }
