"""The shop's rules besides the order path: prices today, shipments and stock levels.

The cart, checkout, the payments and refunds are karni-commerce's
(``karni_commerce.services``). The shop decides what a product costs and how its
stock moves (shop/sellables.py) and what happens to the parcel (here).

The shop's settings are on the Settings page (shop/preferences.py): the low-stock
level, what shoppers see of the stock, reviews, related products and downloads. The
project's ``SHOP_LOW_STOCK``, ``SHOP_REVIEWS_NEED_APPROVAL`` and ``SHOP_RELATED_COUNT``
are their first values. ``SHOP_STAFF_EMAILS`` names who gets the low-stock email (else
the Checkout settings' staff emails).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core import signing
from django.db import models, transaction
from django.db.models import (
    Case,
    DecimalField,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Sum,
    When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone
from karni_commerce import preferences_seam as preferences
from karni_commerce.models import Order

from shop.models import Download, Product, Review, Shipment, Variation

#: The money states of an order whose buyer paid for what they got.
PAID = ("paid", "part_paid", "part_refunded")


def low_stock_level() -> int:
    """Settings, Shop: the level a product runs low at (``SHOP_LOW_STOCK`` at first)."""
    return preferences.value(
        "shop.low_stock", int(getattr(settings, "SHOP_LOW_STOCK", 3))
    )


def staff_emails() -> list[str]:
    found = getattr(settings, "SHOP_STAFF_EMAILS", None)
    if found is None:
        from karni_commerce.services import staff_emails as commerce_staff

        return commerce_staff()
    return [str(address) for address in found or []]


def with_effective_price(queryset: QuerySet[Product]) -> QuerySet[Product]:
    """Each product with ``effective_price``: what a customer pays now (on sale too)."""
    now = timezone.now()
    on_sale = (
        Q(sale_price__isnull=False)
        & (Q(sale_starts__isnull=True) | Q(sale_starts__lte=now))
        & (Q(sale_ends__isnull=True) | Q(sale_ends__gt=now))
    )
    return queryset.annotate(
        effective_price=Case(
            When(on_sale, then=F("sale_price")),
            default=F("price"),
            output_field=DecimalField(max_digits=19, decimal_places=4),
        )
    )


def with_stock(queryset: QuerySet[Product]) -> QuerySet[Product]:
    """Each product with its stock as a shopper and staff read it.

    ``stock_total`` and ``available_total`` are the product's own ``stock`` and
    ``available``, or for a product with active variations the sum of theirs: such a
    product is bought by its variations, so its own figures do not move.
    ``has_variations`` says which. The product list, its filters, the home tiles and
    the API all read these, so "Sold out" and "Running low" follow the variations.
    """
    active = Variation.objects.filter(product=OuterRef("pk"), active=True)

    def total(field: str) -> Coalesce:
        summed = (
            active.order_by()
            .values("product")
            .annotate(total=Sum(field))
            .values("total")[:1]
        )
        return Coalesce(
            Subquery(summed, output_field=IntegerField()),
            F(field),
            output_field=IntegerField(),
        )

    return queryset.annotate(
        has_variations=Exists(active),
        stock_total=total("stock"),
        available_total=total("available"),
    )


def ships(order: Order) -> bool:
    """Whether the order has products to send (a shipment of its own)."""
    return order.lines.filter(kind="product", needs_shipping=True).exists()


@transaction.atomic
def open_shipment(order: Order) -> Shipment | None:
    """The paid order's parcel, waiting to be sent (one per order)."""
    if not ships(order):
        return None
    found = Shipment.objects.filter(order=order).first()
    return found or Shipment.objects.create(order=order, status="processing")


@transaction.atomic
def ship(shipment: Shipment, tracking_number: str, carrier: str = "") -> Shipment:
    """Mark the parcel sent, with its tracking number (the buyer gets an email)."""
    shipment.transition(
        "status", "shipped", tracking_number=tracking_number, carrier=carrier
    )
    return shipment


@transaction.atomic
def deliver(shipment: Shipment) -> Shipment:
    """Mark the parcel delivered (the buyer gets an email)."""
    shipment.transition("status", "delivered")
    return shipment


def cancel_shipment(order: Order) -> None:
    """The order was cancelled: a parcel not sent yet will not be."""
    for shipment in Shipment.objects.filter(order=order, status="processing"):
        shipment.transition("status", "cancelled")


def shipment_context(shipment: Any) -> dict[str, Any]:
    from karni_commerce.services import order_link

    order = shipment.order
    return {
        "shipment": shipment,
        "order": order,
        "lines": list(order.lines.filter(kind="product")),
        "link": order_link(order),
    }


def reviews_need_approval() -> bool:
    return preferences.value("shop.reviews_need_approval", True)


def related_count() -> int:
    return preferences.value("shop.related_count", 4)


def received(user: Any, product: Product) -> bool:
    """Whether ``user`` paid for ``product`` (any variation) and its parcel arrived."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    orders = Order.objects.filter(
        user=user,
        status__in=PAID,
        lines__kind="product",
        lines__item=str(product.pk),
    )
    return Shipment.objects.filter(order__in=orders, status="delivered").exists()


def review_problem(user: Any, product: Product) -> str:
    """Why ``user`` may not review ``product``, in words, or "" when they may."""
    if user is None or not getattr(user, "is_authenticated", False):
        return "Sign in to review a product you bought."
    if Review.objects.filter(product=product, author=user).exists():
        return "You have reviewed this product."
    if not received(user, product):
        return "You can review a product once it has reached you."
    return ""


def related(product: Product, count: int | None = None) -> list[Product]:
    """The products to show beside ``product``: staff's choice, then its category's.

    Active products only, never the product itself. Staff's choices come first in
    their order, and the rest are the same categories' best rated and featured.
    """
    wanted = related_count() if count is None else count
    chosen = list(
        product.related.filter(active=True).exclude(pk=product.pk).order_by("name")
    )[:wanted]
    if len(chosen) < wanted:
        more = (
            Product.objects.filter(active=True, categories__in=product.categories.all())
            .exclude(pk__in=[product.pk, *[row.pk for row in chosen]])
            .order_by("-featured", "-rating_average", "name")
            .distinct()
        )
        chosen += list(more[: wanted - len(chosen)])
    return chosen


# -- digital products ------------------------------------------------------------------


#: The salt of a download link's signature.
DOWNLOAD_SALT = "shop.download"


def grant_downloads(order: Order) -> list[Download]:
    """The paid order's digital products: a download per file, counted and dated.

    Each allows the product's ``download_limit`` (else Settings, Shop) and works for
    its ``download_days`` (0: always). Asking twice changes nothing.
    """
    lines = order.lines.filter(kind="product")
    products = Product.objects.filter(
        pk__in=[line.item for line in lines], digital=True
    ).prefetch_related("productfile_set")
    found: list[Download] = []
    now = timezone.now()
    for product in products:
        limit = product.download_limit or preferences.value("shop.download_limit", 5)
        days = product.download_days
        if days is None:
            days = preferences.value("shop.download_days", 30)
        for file in product.productfile_set.all():
            row, _ = Download.objects.get_or_create(
                order=order,
                file=file,
                defaults={
                    "product": product,
                    "email": order.email,
                    "downloads": 0,
                    "limit": limit,
                    "expires_at": now + timedelta(days=days) if days else None,
                },
            )
            found.append(row)
    return found


def download_link(download: Download) -> str:
    """The signed link that hands the file to whoever has it (the buyer's email)."""
    token = signing.dumps(str(download.pk), salt=DOWNLOAD_SALT)
    frontend = str(getattr(settings, "KARNI_FRONTEND_URL", "") or "").rstrip("/")
    return f"{frontend}/api/downloads/get/{token}/"


def download_problem(download: Download, now: Any = None) -> str:
    """Why the download no longer works, in words, or "" when it does."""
    order = download.order
    if order.status not in ("paid", "part_refunded"):
        return "This order is no longer paid, so its downloads have stopped."
    refunded = order.lines.filter(
        kind="product",
        item=str(download.product_id),
        quantity_refunded__gte=models.F("quantity"),
    ).exists()
    if refunded:
        return "This product was refunded, so its download has stopped."
    if download.expires_at is not None and download.expires_at <= (
        now or timezone.now()
    ):
        return "This download link has expired."
    if download.limit is not None and download.downloads >= download.limit:
        return f"This file was downloaded {download.downloads} times, the most allowed."
    return ""


@transaction.atomic
def take_download(token: str) -> Download:
    """Count one download of the file the signed ``token`` names, or say why not.

    The row is locked while it is counted, so two clicks at once never pass the limit.

    :raises PermissionDenied: for a link that was changed or no longer works.
    """
    from rest_framework.exceptions import PermissionDenied

    try:
        pk = signing.loads(token, salt=DOWNLOAD_SALT)
    except signing.BadSignature:
        raise PermissionDenied("That is not a download link of this shop.") from None
    download = (
        Download.objects.select_for_update()
        .select_related("order", "file")
        .filter(pk=pk)
        .first()
    )
    if download is None:
        raise PermissionDenied("That is not a download link of this shop.")
    problem = download_problem(download)
    if problem:
        raise PermissionDenied(problem)
    download.downloads += 1
    download.last_at = timezone.now()
    download.save(update_fields=["downloads", "last_at", "updated_at"])
    return download
