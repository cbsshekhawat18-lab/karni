"""What the selling apps report about an order's goods, for its buyer's page.

An order holds the money. What happens to the goods (a parcel shipped, a
booking confirmed) is the selling app's own record, so commerce asks the
apps: each registers a reporter that answers a few plain entries for an
order, and the order's page shows them::

    # shop/sellables.py
    from karni_commerce.fulfilment import register_reporter


    @register_reporter
    def shipments(order):
        for shipment in Shipment.objects.filter(order=order):
            yield {"title": "Parcel", "status": shipment.status,
                   "label": "Shipped", "detail": f"Tracking {shipment.tracking}",
                   "at": shipment.shipped_at}

Each entry has ``title``, ``status`` (a short name), ``label`` (the status
in words), ``detail`` (optional), ``at`` (a datetime or ``None``) and, when
the buyer may follow it, ``link`` with ``link_label`` (a download, a ticket).

Override / escape hatch: :func:`unregister_reporter` takes one out.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from karni_commerce.models import Order

__all__ = ["Reporter", "register_reporter", "report", "unregister_reporter"]

Reporter = Callable[["Order"], Iterable[Mapping[str, Any]]]

_REPORTERS: list[Reporter] = []


def register_reporter(reporter: Reporter) -> Reporter:
    """Add ``reporter`` (usable as a decorator). Registering it twice is a no-op."""
    if reporter not in _REPORTERS:
        _REPORTERS.append(reporter)
    return reporter


def unregister_reporter(reporter: Reporter) -> None:
    """Take ``reporter`` out."""
    if reporter in _REPORTERS:
        _REPORTERS.remove(reporter)


def report(order: Order) -> list[dict[str, Any]]:
    """Every reporter's entries for ``order``, in registration order."""
    found: list[dict[str, Any]] = []
    for reporter in _REPORTERS:
        for entry in reporter(order):
            at = entry.get("at")
            found.append(
                {
                    "title": str(entry.get("title", "")),
                    "status": str(entry.get("status", "")),
                    "label": str(entry.get("label", entry.get("status", ""))),
                    "detail": str(entry.get("detail", "") or ""),
                    "at": at.isoformat() if isinstance(at, datetime) else None,
                    "link": str(entry.get("link", "") or ""),
                    "link_label": str(entry.get("link_label", "") or ""),
                }
            )
    return found
