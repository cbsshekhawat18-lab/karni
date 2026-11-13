"""Experimental. The shop owner's reports: tables of what sold, by date, item, coupon.

A report is a function that answers a table for a date range: its columns,
its rows and the totals. Commerce gives the ones every seller has (sales by
date, by item, the coupons used), and a selling app adds its own in its
``<app>/reports.py`` (imported at startup)::

    from karni_commerce.reports import Column, register_report


    @register_report(
        key="shop.stock", title="Stock", requires="shop.product:view", dated=False
    )
    def stock(query):
        return {"columns": [Column("name", "Product")], "rows": [...]}

``GET /api/orders/reports/`` lists the reports the caller may run, and
``GET /api/orders/reports/<key>/?start=&end=&by=day`` runs one, as JSON or,
with ``?export=csv``, as a CSV file. Every figure is the server's.

A report covers the orders paid in the range: ``paid``, ``part_paid``,
``part_refunded`` and ``refunded`` (a refunded order was paid, and its refund
shows in the refunds column). Days are the project's time zone.

karni-reports prints one record to PDF (an invoice, :mod:`karni_commerce.invoices`).
These are tables, so they export to CSV, the format a spreadsheet or an
accountant reads.

Override / escape hatch: :func:`unregister_report` takes one out, and a
report of the same key registered later replaces it.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Count, F, Q, QuerySet, Sum
from django.db.models.functions import Coalesce, TruncDay, TruncMonth, TruncWeek
from django.utils import timezone

from karni_commerce import conf
from karni_commerce.models import ZERO, CouponUse, Order, OrderLine

__all__ = [
    "PAID",
    "Column",
    "Report",
    "ReportQuery",
    "as_csv",
    "find_report",
    "paid_orders",
    "register_report",
    "reports_for",
    "run",
    "unregister_report",
]

#: The money states of an order that was paid (some of it may have gone back since).
PAID = ("paid", "part_paid", "part_refunded", "refunded")

#: How a range may be split into rows.
BUCKETS = {"day": TruncDay, "week": TruncWeek, "month": TruncMonth}


@dataclass(frozen=True)
class Column:
    """Experimental. One column: its key in each row, its heading and how it shows."""

    key: str
    label: str
    format: str = "text"  # text, number, money, date

    def as_dict(self) -> dict[str, str]:
        return {"key": self.key, "label": self.label, "format": self.format}


@dataclass(frozen=True)
class ReportQuery:
    """Experimental. What a report is asked for: a range of days and how to split it."""

    start: date
    end: date
    by: str = "day"
    request: Any = None

    @property
    def since(self) -> datetime:
        return timezone.make_aware(datetime.combine(self.start, time.min))

    @property
    def until(self) -> datetime:
        return timezone.make_aware(datetime.combine(self.end + timedelta(days=1), time.min))


Source = Callable[[ReportQuery], Mapping[str, Any]]


@dataclass(frozen=True)
class Report:
    """Experimental. A registered report: who may run it and the function that answers it."""

    key: str
    title: str
    source: Source
    requires: str = "karni_commerce.order:view"
    describe: str = ""
    dated: bool = True
    order: int = 100
    extra: dict[str, Any] = field(default_factory=dict)

    def visible_to(self, user: Any) -> bool:
        from karni.navigation import opens

        return bool(opens(self.requires, user))


_REPORTS: dict[str, Report] = {}
_DISCOVERED = [False]


def register_report(
    *,
    key: str,
    title: str,
    requires: str = "karni_commerce.order:view",
    describe: str = "",
    dated: bool = True,
    order: int = 100,
) -> Callable[[Source], Source]:
    """Experimental. Register the decorated function as the report ``key``."""

    def wrap(source: Source) -> Source:
        _REPORTS[key] = Report(
            key=key,
            title=title,
            source=source,
            requires=requires,
            describe=describe or (source.__doc__ or "").strip().split("\n")[0],
            dated=dated,
            order=order,
        )
        return source

    return wrap


def unregister_report(key: str) -> None:
    _REPORTS.pop(key, None)


def _discover() -> None:
    if not _DISCOVERED[0]:
        _DISCOVERED[0] = True
        from django.utils.module_loading import autodiscover_modules

        autodiscover_modules("reports")


def find_report(key: str) -> Report | None:
    _discover()
    return _REPORTS.get(key)


def reports_for(user: Any) -> list[Report]:
    """Experimental. The reports ``user`` may run, in order."""
    _discover()
    found = [report for report in _REPORTS.values() if report.visible_to(user)]
    return sorted(found, key=lambda report: (report.order, report.title))


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return f"{value.quantize(Decimal('0.01'))}"
    if isinstance(value, datetime):
        return timezone.localtime(value).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def run(report: Report, query: ReportQuery) -> dict[str, Any]:
    """Experimental. The report's answer: columns, rows and totals, as plain values."""
    found = dict(report.source(query))
    columns = [
        column.as_dict() if isinstance(column, Column) else dict(column)
        for column in found.get("columns", [])
    ]
    rows = [{key: _plain(value) for key, value in row.items()} for row in found.get("rows", [])]
    totals = {key: _plain(value) for key, value in dict(found.get("totals") or {}).items()}
    return {
        "key": report.key,
        "title": report.title,
        "describe": report.describe,
        "dated": report.dated,
        "start": query.start.isoformat() if report.dated else None,
        "end": query.end.isoformat() if report.dated else None,
        "by": query.by if report.dated else None,
        "currency": conf.currency().upper(),
        "columns": columns,
        "rows": rows,
        "totals": totals,
    }


def as_csv(answer: Mapping[str, Any]) -> str:
    """Experimental. A report's answer as CSV: a heading row, the rows, then the totals."""
    columns = list(answer["columns"])
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([column["label"] for column in columns])
    for row in answer["rows"]:
        writer.writerow([_cell(row.get(column["key"])) for column in columns])
    totals = answer.get("totals") or {}
    if totals:
        first = columns[0]["key"] if columns else ""
        writer.writerow(
            [
                "Total" if column["key"] == first else _cell(totals.get(column["key"]))
                for column in columns
            ]
        )
    return out.getvalue()


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    # A cell a spreadsheet would run as a formula is written as text.
    return f"'{text}" if text[:1] in ("=", "+", "-", "@") and not _number(text) else text


def _number(text: str) -> bool:
    try:
        Decimal(text)
    except ArithmeticError:
        return False
    return True


# -- the orders a report counts --------------------------------------------------------------


def paid_orders(query: ReportQuery) -> QuerySet[Order]:
    """Experimental. The orders paid in the range (some may be refunded since)."""
    return Order.objects.filter(status__in=PAID, paid_at__gte=query.since, paid_at__lt=query.until)


def _money_sum(name: str) -> Any:
    return Coalesce(Sum(name), ZERO)


def _sum(rows: Iterable[Mapping[str, Any]], key: str) -> Any:
    return sum((row.get(key) or 0 for row in rows), Decimal("0") if key != "orders" else 0)


@register_report(
    key="commerce.sales_by_date",
    title="Sales by date",
    describe="Orders paid each day, week or month: items, discounts, shipping, tax, refunds.",
    order=10,
)
def sales_by_date(query: ReportQuery) -> dict[str, Any]:
    bucket = BUCKETS.get(query.by, TruncDay)
    rows = list(
        paid_orders(query)
        .annotate(period=bucket("paid_at"))
        .values("period")
        .annotate(
            orders=Count("pk"),
            gross=_money_sum("subtotal"),
            discounts=_money_sum("discount_total"),
            shipping=_money_sum("shipping_total"),
            tax=_money_sum("tax_total"),
            total=_money_sum("total"),
            refunds=_money_sum("amount_refunded"),
        )
        .order_by("period")
    )
    for row in rows:
        row["net"] = row["total"] - row["refunds"]
    money = ("gross", "discounts", "shipping", "tax", "total", "refunds", "net")
    return {
        "columns": [
            Column("period", "Date", "date"),
            Column("orders", "Orders", "number"),
            Column("gross", "Items", "money"),
            Column("discounts", "Discounts", "money"),
            Column("shipping", "Shipping", "money"),
            Column("tax", "Tax", "money"),
            Column("total", "Paid", "money"),
            Column("refunds", "Refunds", "money"),
            Column("net", "Net", "money"),
        ],
        "rows": rows,
        "totals": {"orders": _sum(rows, "orders"), **{key: _sum(rows, key) for key in money}},
    }


@register_report(
    key="commerce.sales_by_item",
    title="Sales by item",
    describe="What sold in the range, by item: how many, what it brought in, less refunds.",
    order=20,
)
def sales_by_item(query: ReportQuery) -> dict[str, Any]:
    lines = OrderLine.objects.filter(order__in=paid_orders(query))
    rows = list(
        lines.values("kind", "item")
        .annotate(
            name=Coalesce(_first_name(), F("item")),
            sold=Coalesce(Sum("quantity"), 0),
            refunded=Coalesce(Sum("quantity_refunded"), 0),
            gross=_money_sum("line_total"),
            discounts=_money_sum("discount"),
        )
        .order_by("-gross", "kind", "item")
    )
    for row in rows:
        row["net"] = row["gross"] - row["discounts"]
        row["kept"] = row["sold"] - row["refunded"]
    return {
        "columns": [
            Column("name", "Item"),
            Column("kind", "Kind"),
            Column("sold", "Sold", "number"),
            Column("refunded", "Refunded", "number"),
            Column("gross", "Sales", "money"),
            Column("discounts", "Discounts", "money"),
            Column("net", "Net", "money"),
        ],
        "rows": rows,
        "totals": {
            "sold": sum(row["sold"] for row in rows),
            "refunded": sum(row["refunded"] for row in rows),
            "gross": _sum(rows, "gross"),
            "discounts": _sum(rows, "discounts"),
            "net": _sum(rows, "net"),
        },
    }


def _first_name() -> Any:
    from django.db.models import Max

    # One name per item (the latest spelling): the lines copy it at checkout.
    return Max("name")


@register_report(
    key="commerce.coupons",
    title="Coupons used",
    describe="Each coupon used on an order paid in the range: how often, and what it took off.",
    order=30,
)
def coupons(query: ReportQuery) -> dict[str, Any]:
    rows = list(
        CouponUse.objects.filter(order__in=paid_orders(query))
        .values(code=F("coupon__code"), kind=F("coupon__kind"))
        .annotate(
            uses=Count("pk"),
            discount=_money_sum("amount"),
            sales=_money_sum("order__total"),
        )
        .order_by("-uses", "code")
    )
    return {
        "columns": [
            Column("code", "Coupon"),
            Column("kind", "Kind"),
            Column("uses", "Orders", "number"),
            Column("discount", "Taken off", "money"),
            Column("sales", "Orders' total", "money"),
        ],
        "rows": rows,
        "totals": {
            "uses": sum(row["uses"] for row in rows),
            "discount": _sum(rows, "discount"),
            "sales": _sum(rows, "sales"),
        },
    }


def default_range(today: date | None = None) -> tuple[date, date]:
    """The last 30 days, today included."""
    end = today or timezone.localdate()
    return end - timedelta(days=29), end


def filter_paid(query: ReportQuery, rows: QuerySet[Any], path: str = "order") -> QuerySet[Any]:
    """``rows`` narrowed to those of orders paid in the range (``path`` names the order)."""
    return rows.filter(
        Q(**{f"{path}__status__in": PAID})
        & Q(**{f"{path}__paid_at__gte": query.since, f"{path}__paid_at__lt": query.until})
    )
