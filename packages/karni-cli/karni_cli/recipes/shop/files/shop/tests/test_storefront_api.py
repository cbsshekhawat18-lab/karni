"""The shop's API per role: a visitor, a customer, another customer, staff, a manager."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from karni.testing.api import user_with_roles
from karni_commerce.models import Order

from shop.models import Product, Shipment
from shop.tests.conftest import ADDRESS, cart_with, checkout, pay, place, put

pytestmark = pytest.mark.django_db

MakeProduct = Callable[..., Product]


def test_a_visitor_cart_lives_by_its_token(
    client_as: Any, make_product: MakeProduct
) -> None:
    visitor, other = client_as(None), client_as(None)
    lamp = make_product(name="Lamp", price=Decimal("12.50"))
    answer = put(visitor, lamp, 2)
    assert answer.status_code == 200, answer.content
    token = answer.json()["token"]
    assert token and answer.json()["subtotal"] == "25.00"
    [line] = answer.json()["lines"]
    assert (line["name"], line["url"]) == ("Lamp", f"/shop/products/{lamp.slug}")
    mine = visitor.get("/api/carts/current/", HTTP_X_CART_TOKEN=token).json()
    assert [row["quantity"] for row in mine["lines"]] == [2]
    assert other.get("/api/carts/current/").json()["lines"] == []
    assert put(visitor, lamp, 0, token).json()["lines"] == []


def test_a_cart_takes_no_more_than_is_left(
    client_as: Any, make_product: MakeProduct
) -> None:
    answer = put(client_as(None), make_product(stock=2), 3)
    assert answer.status_code == 400 and "Only 2" in str(answer.json())


def test_a_guest_checks_out_and_reads_the_order_by_its_key(
    client_as: Any, make_product: MakeProduct
) -> None:
    visitor = client_as(None)
    token = put(visitor, make_product(price=Decimal("9.00")), 2).json()["token"]
    placed = checkout(visitor, token, note="Ring twice")
    assert placed.status_code == 201, placed.content
    body = placed.json()
    assert body["url"].startswith("https://checkout.test/pay/")
    found = visitor.get(
        "/api/orders/lookup/", {"number": body["number"], "key": body["key"]}
    )
    assert found.status_code == 200
    assert (found.json()["total"], found.json()["note"]) == ("18.00", "Ring twice")
    nobody = client_as(None).get("/api/orders/lookup/", {"number": body["number"]})
    assert nobody.status_code == 404


def test_a_customer_reads_only_their_own_orders(
    client_as: Any, make_product: MakeProduct
) -> None:
    mira = user_with_roles("customer", email="mira@example.com")
    noor = user_with_roles("customer", email="noor@example.com")
    mine = place(cart_with((make_product(), 1)), email=mira.email, user=mira)
    theirs = place(cart_with((make_product(), 1)), email=noor.email, user=noor)
    client = client_as(user=mira)
    listed = client.get("/api/orders/", {"mine": "true"}).json()["results"]
    assert [row["number"] for row in listed] == [mine.number]
    assert client.get(f"/api/orders/{theirs.pk}/").status_code == 404
    assert (
        client.get("/api/orders/lookup/", {"number": theirs.number}).status_code == 404
    )
    assert client.get("/api/shipments/").status_code == 403


def test_customers_change_no_order_product_or_parcel(
    client_as: Any, make_product: MakeProduct
) -> None:
    mira = user_with_roles("customer", email="mira@example.com")
    order = pay(place(cart_with((make_product(), 1)), user=mira, email=mira.email))
    client = client_as(user=mira)
    lamp = make_product()
    assert client.patch(f"/api/products/{lamp.slug}/", {"price": "1.00"}, format="json").status_code == 403
    assert client.post(f"/api/orders/{order.pk}/cancel/").status_code in (403, 404)
    parcel = Shipment.objects.get(order=order)
    assert client.post(f"/api/shipments/{parcel.pk}/ship/", {"tracking_number": "X"}, format="json").status_code in (403, 404)


def test_staff_send_parcels_and_cancel_but_do_not_refund(
    client_as: Any, make_product: MakeProduct
) -> None:
    order = pay(place(cart_with((make_product(), 1))))
    parcel = Shipment.objects.get(order=order)
    staff = client_as("shop-staff")
    assert staff.get("/api/orders/").json()["count"] == 1
    no_number = staff.post(f"/api/shipments/{parcel.pk}/ship/", {}, format="json")
    assert no_number.status_code == 400
    sent = staff.post(
        f"/api/shipments/{parcel.pk}/ship/",
        {"tracking_number": "PP1", "carrier": "Parcel Post"},
        format="json",
    )
    assert sent.status_code == 200, sent.content
    assert sent.json()["status"] == "shipped"
    refund = staff.post(f"/api/orders/{order.pk}/refund/", {"amount": "1.00"}, format="json")
    assert refund.status_code == 403
    other = pay(place(cart_with((make_product(), 1))))
    cancelled = staff.post(f"/api/orders/{other.pk}/cancel/", {}, format="json")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"


def test_a_manager_refunds(client_as: Any, make_product: MakeProduct) -> None:
    order = pay(place(cart_with((make_product(price=Decimal("20.00")), 1))))
    manager = client_as("shop-manager")
    answer = manager.post(
        f"/api/orders/{order.pk}/refund/", {"amount": "5.00"}, format="json"
    )
    assert answer.status_code == 200, answer.content
    assert order.refunds.get().amount == Decimal("5.00")


def test_a_visitor_sees_active_products_and_staff_see_all(
    client_as: Any, make_product: MakeProduct
) -> None:
    shown, hidden = make_product(name="Shown"), make_product(name="Hidden", active=False)
    names = {row["name"] for row in client_as(None).get("/api/products/").json()["results"]}
    assert "Shown" in names and "Hidden" not in names
    assert client_as(None).get(f"/api/products/{hidden.slug}/").status_code == 404
    staff = {row["name"] for row in client_as("shop-staff").get("/api/products/").json()["results"]}
    assert {shown.name, hidden.name} <= staff


def test_the_catalogue_filters_by_price_today_and_sorts_by_it(
    client_as: Any, make_product: MakeProduct
) -> None:
    make_product(name="Cheap", price=Decimal("5.00"))
    make_product(name="Dear", price=Decimal("50.00"))
    visitor = client_as(None)
    found = visitor.get("/api/products/", {"min_price": "10", "ordering": "-effective_price"})
    assert [row["name"] for row in found.json()["results"]] == ["Dear"]
    assert visitor.get("/api/products/", {"min_price": "x"}).status_code == 400


def test_the_catalogue_reads_in_the_same_queries_for_more_products(
    client_as: Any, make_product: MakeProduct
) -> None:
    visitor = client_as(None)
    for _ in range(3):
        make_product()
    with CaptureQueriesContext(connection) as few:
        visitor.get("/api/products/")
    for _ in range(12):
        make_product()
    with CaptureQueriesContext(connection) as many:
        visitor.get("/api/products/")
    assert len(many) == len(few)


def test_signing_in_claims_the_guest_orders_of_a_verified_email(
    client_as: Any, make_product: MakeProduct
) -> None:
    order = place(cart_with((make_product(), 1)), email="mira@example.com")
    mira = user_with_roles("customer", email="mira@example.com", email_verified=True)
    merged = client_as(user=mira).post("/api/carts/current/merge/", {"token": ""}, format="json")
    assert merged.status_code == 200
    assert Order.objects.get(pk=order.pk).user == mira


def test_checkout_takes_no_price_from_the_client(
    client_as: Any, make_product: MakeProduct
) -> None:
    visitor = client_as(None)
    token = put(visitor, make_product(price=Decimal("20.00")), 1).json()["token"]
    placed = checkout(visitor, token, total="0.01", price="0.01", billing=ADDRESS)
    assert Order.objects.get(number=placed.json()["number"]).total == Decimal("20.00")
