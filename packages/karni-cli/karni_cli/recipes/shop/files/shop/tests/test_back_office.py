"""The back office per role: home tiles, orders, refunds, parcels, customers, stock."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from karni.testing.api import user_with_roles
from karni_commerce import services as commerce
from karni_commerce.models import Order, OrderLine

from shop.models import Product, Shipment
from shop.tests.conftest import ADDRESS, cart_with, pay, place

pytestmark = pytest.mark.django_db

MakeProduct = Callable[..., Product]


def refund_went_through(order: Order) -> None:
    """The provider's word that the order's refund went through (its webhook)."""
    from karni_payments.models import WebhookEvent
    from karni_payments.tasks import process_webhook_event

    link = order.payments.order_by("-created_at").first()
    assert link is not None
    payment = link.payment
    event = WebhookEvent.objects.create(
        provider="test",
        event_id=f"evt_refund_{order.number}",
        event_type="refund",
        payload={
            "type": "refund",
            "status": "refund_succeeded",
            "checkout_session_id": payment.checkout_session_id,
        },
    )
    process_webhook_event(str(event.pk))


def tiles(client: Any) -> dict[str, dict[str, Any]]:
    answer = client.get("/api/dashboard/")
    assert answer.status_code == 200, answer.content
    return {tile["key"]: tile for tile in answer.json()["tiles"]}


def test_each_role_sees_its_own_home_tiles(
    client_as: Any, make_product: MakeProduct
) -> None:
    lamp = make_product(price=Decimal("20.00"), stock=4)
    pay(place(cart_with((lamp, 2))))
    staff = tiles(client_as("shop-staff"))
    assert {
        "shop.to_send",
        "shop.in_transit",
        "shop.sold_out",
        "commerce.revenue",
        "commerce.revenue_chart",
        "commerce.latest_orders",
        "shop.low_stock",
        "shop.top_products",
    } <= set(staff)
    assert staff["shop.to_send"]["resource"] == "shipments"
    assert staff["shop.to_send"]["filters"] == {"status": "processing"}
    values = {
        row["label"]: row["value"]
        for row in staff["commerce.revenue"]["data"]["values"]
    }
    assert values["Today"] == "40.00"
    [best] = staff["shop.top_products"]["data"]["rows"]
    assert (best["name"], best["sold"]) == (lamp.name, 2)
    [low] = staff["shop.low_stock"]["data"]["rows"]  # 2 left, at most 3
    assert (low["name"], low["available"]) == (lamp.name, 2)
    assert tiles(client_as("customer")) == {}
    assert tiles(client_as(None)) == {}


def test_a_product_runs_low_at_its_own_level(
    client_as: Any, make_product: MakeProduct
) -> None:
    make_product(name="Kettle", stock=6, low_stock=8)
    make_product(name="Pan", stock=6)
    rows = tiles(client_as("shop-manager"))["shop.low_stock"]["data"]["rows"]
    assert [row["name"] for row in rows] == ["Kettle"]


def test_staff_find_an_order_ship_it_and_the_buyer_reads_the_tracking(
    client_as: Any, make_product: MakeProduct
) -> None:
    order = pay(place(cart_with((make_product(), 1)), email="mira@example.com"))
    staff = client_as("shop-staff")
    found = staff.get("/api/orders/", {"search": str(order.number)}).json()
    assert [row["number"] for row in found["results"]] == [order.number]
    by_state = staff.get("/api/orders/", {"status": "paid"}).json()["count"]
    assert by_state == 1
    parcel = staff.get("/api/shipments/", {"order": str(order.pk)}).json()["results"]
    sent = staff.post(
        f"/api/shipments/{parcel[0]['id']}/ship/",
        {"tracking_number": "PP77", "carrier": "Parcel Post"},
        format="json",
    )
    assert sent.status_code == 200, sent.content
    seen = client_as(None).get(
        "/api/orders/lookup/", {"number": order.number, "key": order.key}
    )
    assert "PP77" in seen.json()["fulfilment"][0]["detail"]


def test_a_manager_refunds_part_of_an_order_back_into_stock(
    client_as: Any, make_product: MakeProduct, django_capture_on_commit_callbacks: Any
) -> None:
    lamp = make_product(price=Decimal("15.00"), stock=5)
    order = pay(place(cart_with((lamp, 3))))
    line = order.lines.get()
    with django_capture_on_commit_callbacks(execute=True):
        answer = client_as("shop-manager").post(
            f"/api/orders/{order.pk}/refund/",
            {"lines": {str(line.pk): 1}, "restock": True, "reason": "Chipped"},
            format="json",
        )
    assert answer.status_code == 200, answer.content
    refund_went_through(order)
    order.refresh_from_db()
    lamp.refresh_from_db()
    assert (order.status, order.amount_refunded) == ("part_refunded", Decimal("15.00"))
    assert (lamp.stock, lamp.available) == (3, 3)


def test_staff_place_an_order_by_hand_and_customers_may_not(
    client_as: Any, make_product: MakeProduct
) -> None:
    lamp = make_product(price=Decimal("12.00"), stock=4)
    body = {
        "email": "phone@example.com",
        "billing": ADDRESS,
        "lines": [{"kind": "product", "item": str(lamp.pk), "quantity": 2}],
    }
    placed = client_as("shop-staff").post("/api/orders/manual/", body, format="json")
    assert placed.status_code == 201, placed.content
    order = Order.objects.get(number=placed.json()["number"])
    assert (order.total, order.status) == (Decimal("24.00"), "pending")
    lamp.refresh_from_db()
    assert lamp.available == 2
    found = client_as("shop-staff").get("/api/orders/items/", {"search": lamp.sku})
    assert [row["name"] for row in found.json()] == [lamp.name]
    customer = client_as("customer")
    assert customer.post("/api/orders/manual/", body, format="json").status_code == 403
    assert customer.get("/api/orders/customers/").status_code == 403


def test_staff_read_the_customers_and_a_customer_page(
    client_as: Any, make_product: MakeProduct
) -> None:
    mira = user_with_roles("customer", email="mira@example.com")
    lamp = make_product(price=Decimal("10.00"), stock=10)
    pay(place(cart_with((lamp, 2)), email=mira.email, user=mira))
    staff = client_as("shop-staff")
    rows = staff.get("/api/orders/customers/").json()["results"]
    assert [(row["email"], row["spent"]) for row in rows] == [(mira.email, "20.00")]
    page = staff.get("/api/orders/customer/", {"email": mira.email}).json()
    assert page["order_count"] == 1 and page["addresses"]


def test_a_product_with_backorders_sells_past_its_stock(
    make_product: MakeProduct,
) -> None:
    mug = make_product(stock=1, backorders=True)
    order = pay(place(cart_with((mug, 3))))
    mug.refresh_from_db()
    assert (mug.stock, mug.available) == (0, 0)  # one came off the shelf, two wait
    assert OrderLine.objects.get(order=order).options == {"_held": 1}
    commerce.cancel(order)
    mug.refresh_from_db()
    assert (mug.stock, mug.available) == (1, 1)  # only the one that was taken goes back


def test_without_backorders_the_last_one_is_the_limit(
    make_product: MakeProduct,
) -> None:
    from rest_framework.exceptions import ValidationError

    plate = make_product(stock=1)
    with pytest.raises(ValidationError):
        cart_with((plate, 2))


def test_the_orders_list_reads_in_the_same_queries_for_more_orders(
    client_as: Any, make_product: MakeProduct
) -> None:
    lamp = make_product(stock=40)
    staff = client_as("shop-staff")
    for _ in range(2):
        place(cart_with((lamp, 1)))
    staff.get("/api/orders/")
    with CaptureQueriesContext(connection) as few:
        staff.get("/api/orders/", {"expand": "user"})
    for _ in range(10):
        place(cart_with((lamp, 1)))
    with CaptureQueriesContext(connection) as many:
        staff.get("/api/orders/", {"expand": "user"})
    assert len(many) == len(few)


def test_the_shipments_list_names_each_order_by_its_number(
    client_as: Any, make_product: MakeProduct
) -> None:
    order = pay(place(cart_with((make_product(), 1)), email="mira@example.com"))
    rows = client_as("shop-staff").get("/api/shipments/", {"expand": "order"}).json()
    assert rows["results"][0]["order"]["number"] == order.number
    assert Shipment.objects.count() == 1
