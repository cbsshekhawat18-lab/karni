"""Running the shop: its settings, digital products, reports, the emails staff edit."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from django.core import mail
from django.core.files.base import ContentFile
from django.template import Context
from django.template.loader import render_to_string
from karni import preferences
from karni.mail import _engine, kinds, merge_values
from karni.notify.editor import file_source
from karni.notify.models import EmailTemplate
from karni.testing.api import user_with_roles
from karni_commerce import services as commerce
from karni_commerce.models import Cart, Order
from rest_framework.test import APIClient

from shop import services
from shop.models import Category, Download, Product, ProductFile, Shipment
from shop.tests.conftest import ADDRESS, cart_with, pay, place

pytestmark = pytest.mark.django_db

MakeProduct = Callable[..., Product]


def as_role(role: str, email: str = "") -> APIClient:
    client = APIClient()
    client.force_authenticate(
        user_with_roles(role, **({"email": email} if email else {}))
    )
    return client


@pytest.fixture
def booklet(make_product: MakeProduct, settings: Any, tmp_path: Path) -> Product:
    """A digital product with one file, downloaded at most twice."""
    settings.KARNI_STORAGE_ROOT = str(tmp_path)
    product = make_product(
        name="Planner Pages", sku="PDF-1", price=Decimal("6.00"), digital=True, stock=0
    )
    product.download_limit = 2
    product.save()
    row = ProductFile(product=product, name="Planner pages, A4")
    row.file.save("planner.pdf", ContentFile(b"%PDF-1.4 planner"), save=False)
    row.save()
    return product


# -- settings --------------------------------------------------------------------------


def test_the_shop_settings_change_the_catalogue_and_the_stock_alerts(
    make_product: MakeProduct,
) -> None:
    lamp = make_product(name="Lamp", sku="LMP", stock=4, available=4)
    gone = make_product(name="Vase", sku="VSE", stock=0, available=0)
    manager, staff, shopper = (
        as_role("shop-manager"),
        as_role("shop-staff"),
        APIClient(),
    )
    page = manager.get("/api/preferences/")
    assert page.status_code == 200
    shop = next(row for row in page.data["sections"] if row["key"] == "shop")
    assert shop["values"]["low_stock"] == 3 and shop["can_change"] is True
    assert staff.get("/api/preferences/").status_code == 403
    assert not lamp.runs_low()
    changed = manager.patch(
        "/api/preferences/sections/shop/",
        {"low_stock": 5, "hide_sold_out": True, "show_stock_left": False},
        format="json",
    )
    assert changed.status_code == 200, changed.data
    assert Product.objects.get(pk=lamp.pk).runs_low()  # 4 left, low at 5 now
    skus = [row["sku"] for row in shopper.get("/api/products/").data["results"]]
    assert "VSE" not in skus and "LMP" in skus
    row = shopper.get("/api/products/", {"sku": "LMP"}).data["results"][0]
    assert (row["stock_left"], row["runs_low"]) == (None, True)  # the figure is hidden
    staff_skus = [row["sku"] for row in staff.get("/api/products/").data["results"]]
    assert "VSE" in staff_skus  # staff see every product
    assert (
        staff.get("/api/products/", {"sku": "LMP"}).data["results"][0]["stock_left"]
        == 4
    )
    assert (
        staff.patch(
            "/api/preferences/sections/shop/", {"low_stock": 1}, format="json"
        ).status_code
        == 403
    )
    assert gone.pk


def test_the_business_name_reaches_the_emails(
    make_product: MakeProduct, django_capture_on_commit_callbacks: Any
) -> None:
    preferences.save_details(
        {"name": "Corner Shop", "sender_email": "hi@corner.example"}
    )
    order = pay(place(cart_with((make_product(), 1))))
    shipment = Shipment.objects.get(order=order)
    with django_capture_on_commit_callbacks(execute=True):
        services.ship(shipment, "PP123", "Parcel Post")
    [sent] = [
        m
        for m in mail.outbox
        if m.extra_headers["X-Karni-Kind"] == "shop.shipment_shipped"
    ]
    assert sent.from_email == "Corner Shop <hi@corner.example>"
    assert sent.body.rstrip().endswith("Corner Shop")
    assert "Parcel Post tracking number: PP123" in sent.body


# -- emails staff edit -----------------------------------------------------------------


def test_every_shop_email_file_is_an_editable_template_on_its_merge_fields(
    make_product: MakeProduct,
) -> None:
    order = pay(place(cart_with((make_product(name="Lamp"), 2))))
    shipment = Shipment.objects.get(order=order)
    shipment.tracking_number, shipment.carrier = "PP1", "Parcel Post"
    from karni_commerce.messages import business

    product = Product.objects.get(name="Lamp")
    contexts = {
        "shop.shipment_shipped": {
            **services.shipment_context(shipment),
            "business": business(),
        },
        "shop.shipment_delivered": {
            **services.shipment_context(shipment),
            "business": business(),
        },
        "shop.downloads_ready": {
            "order": order,
            "business": business(),
            "link": "https://shop.example.com/orders/1",
            "downloads": [
                {
                    "name": "A4",
                    "product": "Planner",
                    "link": "https://x",
                    "limit": 2,
                    "expires_at": None,
                }
            ],
        },
        "shop.low_stock": {
            "business": business(),
            "stocked": product,
            "name": str(product),
            "level": 3,
        },
    }
    declared = [kind for kind in kinds() if kind.name.startswith("shop.")]
    assert {kind.name for kind in declared} == set(contexts)
    for kind in declared:
        values = merge_values(kind.fields, contexts[kind.name])
        for part in ("subject", "body"):
            source = file_source(kind.template, part)
            restricted = _engine().from_string(source).render(Context(values))
            full = render_to_string(f"{kind.template}_{part}.txt", contexts[kind.name])
            assert restricted == full, (kind.name, part)


def test_an_edited_parcel_email_is_the_one_sent(
    make_product: MakeProduct, django_capture_on_commit_callbacks: Any
) -> None:
    manager = as_role("shop-manager")
    saved = manager.put(
        "/api/email-templates/shop.shipment_shipped/",
        {
            "subject": "On its way: {{ order.number }}",
            "text": "Tracking {{ shipment.tracking_number }}. {{ order.password }}",
        },
        format="json",
    )
    assert saved.status_code == 200, saved.data
    assert as_role("shop-staff").get("/api/email-templates/").status_code == 403
    order = pay(place(cart_with((make_product(), 1))))
    with django_capture_on_commit_callbacks(execute=True):
        services.ship(Shipment.objects.get(order=order), "PP9")
    [sent] = [
        m
        for m in mail.outbox
        if m.extra_headers["X-Karni-Kind"] == "shop.shipment_shipped"
    ]
    assert (sent.subject, sent.body) == (
        f"On its way: {order.number}",
        "Tracking PP9. ",
    )
    assert EmailTemplate.objects.count() == 1


# -- digital products ------------------------------------------------------------------


def test_a_digital_product_is_downloaded_by_its_signed_link_up_to_its_limit(
    booklet: Product, django_capture_on_commit_callbacks: Any
) -> None:
    cart = cart_with((booklet, 1))
    with django_capture_on_commit_callbacks(execute=True):
        order = commerce.checkout(cart, email="ines@example.com", billing=ADDRESS)
        assert order.needs_shipping is False
        pay(order)
    assert not Shipment.objects.filter(order=order).exists()  # nothing to send
    [download] = Download.objects.filter(order=order)
    assert (download.limit, download.downloads, download.email) == (
        2,
        0,
        "ines@example.com",
    )
    [sent] = [
        m
        for m in mail.outbox
        if m.extra_headers["X-Karni-Kind"] == "shop.downloads_ready"
    ]
    link = services.download_link(download)
    assert link in sent.body and "2 times" in sent.body
    path = link.split("shop.example.com", 1)[1]
    visitor = APIClient()
    for count in (1, 2):
        got = visitor.get(path)
        assert got.status_code == 200, got.content
        assert b"".join(got.streaming_content) == b"%PDF-1.4 planner"
        assert "Planner pages, A4.pdf" in got["Content-Disposition"]
        download.refresh_from_db()
        assert download.downloads == count
    third = visitor.get(path)
    assert third.status_code == 403 and "the most allowed" in str(third.data)
    assert visitor.get(path[:-6] + "nope0/").status_code == 403
    fulfilment = (
        APIClient()
        .get("/api/orders/lookup/", {"number": order.number, "key": order.key})
        .data["fulfilment"]
    )
    [entry] = [row for row in fulfilment if row["title"] == "Download"]
    assert entry["link"] == "" and "the most allowed" in entry["detail"]


def test_a_refunded_download_stops_and_staff_read_the_downloads(
    booklet: Product, make_product: MakeProduct
) -> None:
    order = pay(place(cart_with((booklet, 1), (make_product(), 1))))
    [download] = Download.objects.filter(order=order)
    entry = next(
        row
        for row in APIClient()
        .get("/api/orders/lookup/", {"number": order.number, "key": order.key})
        .data["fulfilment"]
        if row["title"] == "Download"
    )
    assert entry["link"] == services.download_link(download)
    assert entry["detail"] == "2 of 2 downloads left"
    assert Shipment.objects.filter(order=order).exists()  # the other product is sent
    line = order.lines.get(item=str(booklet.pk))
    commerce.refund(order, lines={str(line.pk): 1}, restock=False)
    from shop.tests.test_back_office import refund_went_through

    refund_went_through(order)
    order.refresh_from_db()
    assert services.download_problem(download) == (
        "This product was refunded, so its download has stopped."
    )
    staff = as_role("shop-staff")
    rows = staff.get("/api/downloads/").data["results"]
    assert [row["email"] for row in rows] == ["guest@example.com"]
    assert as_role("customer").get("/api/downloads/").status_code == 403


def test_the_cart_holds_no_stock_for_a_file_and_it_never_sells_out(
    booklet: Product,
) -> None:
    cart = Cart.objects.create()
    commerce.set_line(cart, "product", str(booklet.pk), 3)
    order = place(cart)
    booklet.refresh_from_db()
    assert (booklet.stock, booklet.available) == (0, 0)
    pay(order)
    commerce.cancel(order)
    booklet.refresh_from_db()
    assert (booklet.stock, booklet.available) == (0, 0)


# -- reports ---------------------------------------------------------------------------


def test_sales_by_category_counts_a_sale_once_in_a_row_and_in_the_totals(
    make_product: MakeProduct,
) -> None:
    """A product in a parent and in its child counts once in the parent's row (which
    includes its children) and once in the totals."""
    garden = Category.objects.create(name="Garden", slug="garden")
    growing = Category.objects.create(name="Growing", slug="growing", parent=garden)
    tools = Category.objects.create(name="Tools", slug="tools")
    seeds = make_product(name="Seeds", sku="SDS", price=Decimal("5.00"), stock=50)
    seeds.categories.set([garden, growing])  # in the parent and in its child
    trowel = make_product(name="Trowel", sku="TRW", price=Decimal("12.00"), stock=50)
    trowel.categories.set([growing, tools])  # in two trees
    hose = make_product(name="Hose", sku="HSE", price=Decimal("30.00"), stock=50)
    hose.categories.set([garden])
    pay(place(cart_with((seeds, 3), (trowel, 2), (hose, 1))))
    report = as_role("shop-manager").get(
        "/api/orders/reports/shop.sales_by_category/"
    ).data
    rows = {row["category"]: row for row in report["rows"]}
    assert (rows["Garden"]["sold"], rows["Garden"]["sales"]) == (6, "69.00")
    assert rows["Garden"]["includes"] == "Growing"
    assert (rows["Growing"]["sold"], rows["Growing"]["parent"]) == (5, "Garden")
    assert (rows["Tools"]["sold"], rows["Tools"]["sales"]) == (2, "24.00")
    # each sale once: 15 + 24 + 30, though the trowel is in two rows at the top
    assert (report["totals"]["sold"], report["totals"]["sales"]) == (6, "69.00")
    info = next(
        row
        for row in as_role("shop-manager").get("/api/orders/reports/").data
        if row["key"] == "shop.sales_by_category"
    )
    assert "includes the sales of the categories in it" in info["describe"]


def test_the_shop_reports_for_the_manager_only(make_product: MakeProduct) -> None:
    lamp = make_product(
        name="Lamp", sku="LMP", price=Decimal("20.00"), stock=10, available=10
    )
    top = Category.objects.create(name="Lighting", slug="lighting")
    lamps = Category.objects.create(name="Lamps", slug="lamps", parent=top)
    lamp.categories.set([lamps])
    pay(place(cart_with((lamp, 2))))
    place(cart_with((lamp, 1)))  # waiting: not counted
    manager = as_role("shop-manager")
    keys = [row["key"] for row in manager.get("/api/orders/reports/").data]
    assert {"shop.sales_by_category", "shop.stock", "commerce.sales_by_date"} <= set(
        keys
    )
    assert as_role("shop-staff").get("/api/orders/reports/").data == []
    by_category = manager.get("/api/orders/reports/shop.sales_by_category/").data
    assert by_category["totals"]["sales"] == "40.00"
    rows = by_category["rows"]
    assert [(row["category"], row["sold"], row["sales"]) for row in rows] == [
        ("Lighting", 2, "40.00"),
        ("Lamps", 2, "40.00"),
    ]
    assert [row["includes"] for row in rows] == ["Lamps", ""]
    stock = manager.get("/api/orders/reports/shop.stock/").data
    lamp_row = next(row for row in stock["rows"] if row["sku"] == "LMP")
    assert (
        lamp_row["stock"],
        lamp_row["held"],
        lamp_row["available"],
        lamp_row["state"],
    ) == (
        8,
        1,
        7,
        "In stock",
    )
    csv = manager.get("/api/orders/reports/shop.stock/", {"export": "csv"})
    assert csv.content.decode().splitlines()[0].startswith("Product,SKU,State")
    assert Order.objects.count() == 2
