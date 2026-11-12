"""The storefront's API, per role: a visitor, a customer, another customer and staff."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from karni.testing.api import user_with_roles

from shop.models import Cart, Order, Product
from shop.tests.conftest import ADDRESS, checkout, put

pytestmark = pytest.mark.django_db

MakeProduct = Callable[..., Product]


def test_a_visitor_cart_lives_by_its_token(client_as: Any, make_product: MakeProduct) -> None:
    visitor, other = client_as(None), client_as(None)
    lamp = make_product(price=Decimal("12.50"))
    answer = put(visitor, lamp, 2)
    assert answer.status_code == 200, answer.content
    token = answer.json()["token"]
    assert token and answer.json()["count"] == 2 and answer.json()["subtotal"] == "25.00"
    mine = visitor.get("/api/carts/current/", HTTP_X_CART_TOKEN=token).json()
    assert [line["quantity"] for line in mine["lines"]] == [2]
    assert other.get("/api/carts/current/").json()["lines"] == []
    assert put(visitor, lamp, 0, token).json()["lines"] == []


def test_a_cart_takes_no_more_than_is_left(client_as: Any, make_product: MakeProduct) -> None:
    lamp = make_product(stock=2)
    answer = put(client_as(None), lamp, 3)
    assert answer.status_code == 400
    assert "Only 2" in str(answer.json())


def test_signing_in_merges_the_visitor_cart(client_as: Any, make_product: MakeProduct) -> None:
    lamp, mug = make_product(stock=5), make_product(stock=9)
    token = put(client_as(None), lamp, 4).json()["token"]
    put(client_as(None), mug, 1, token)
    customer = client_as("customer")
    put(customer, lamp, 3)
    merged = customer.post("/api/carts/current/merge/", {"token": token}, format="json").json()
    quantities = {line["product"]["id"]: line["quantity"] for line in merged["lines"]}
    assert quantities == {str(lamp.pk): 5, str(mug.pk): 1}  # 4 + 3, capped at the stock
    assert not Cart.objects.filter(token=token).exists()


def test_a_guest_checks_out_and_reads_the_order_by_its_key(
    client_as: Any, make_product: MakeProduct
) -> None:
    guest = client_as(None)
    token = put(guest, make_product(price=Decimal("8.00")), 3).json()["token"]
    answer = checkout(guest, token, total="0.01", subtotal="0.01")  # a total is never read
    assert answer.status_code == 201, answer.content
    number, key = answer.json()["number"], answer.json()["key"]
    order = Order.objects.get(number=number)
    assert order.total == Decimal("24.00") and order.customer is None
    assert order.payment.amount == Decimal("24.00")
    assert answer.json()["url"]
    seen = guest.get("/api/orders/lookup/", {"number": number, "key": key})
    assert seen.status_code == 200 and seen.json()["total"].startswith("24.00")
    assert seen.json()["lines"][0]["quantity"] == 3
    assert guest.get("/api/orders/lookup/", {"number": number, "key": "x"}).status_code == 404
    assert guest.get("/api/orders/lookup/", {"number": number}).status_code == 404


def test_a_customer_reads_and_pays_only_their_own_orders(
    client_as: Any, make_product: MakeProduct
) -> None:
    mira = client_as("customer")
    sam = client_as(user=user_with_roles("customer"))  # another customer
    put(mira, make_product(), 1)
    number = checkout(mira).json()["number"]
    order = Order.objects.get(number=number)
    assert order.customer is not None and order.email == order.customer.email
    assert mira.get("/api/orders/lookup/", {"number": number}).status_code == 200
    assert [row["number"] for row in mira.get("/api/orders/").json()["results"]] == [number]
    assert sam.get("/api/orders/lookup/", {"number": number}).status_code == 404
    assert sam.get(f"/api/orders/{order.pk}/").status_code == 404
    assert sam.post("/api/orders/pay/", {"number": number}, format="json").status_code == 404
    assert mira.post("/api/orders/pay/", {"number": number}, format="json").status_code == 200


def test_customers_cannot_change_orders_or_products(
    client_as: Any, make_product: MakeProduct
) -> None:
    customer = client_as("customer")
    put(customer, make_product(), 1)
    order = Order.objects.get(number=checkout(customer).json()["number"])
    patched = customer.patch(f"/api/orders/{order.pk}/", {"status": "paid"}, format="json")
    assert patched.status_code in (403, 404)
    assert customer.post("/api/products/", {"name": "Free"}, format="json").status_code == 403


def test_staff_move_orders_only_along_the_allowed_moves(
    client_as: Any, make_product: MakeProduct
) -> None:
    put(client_as("customer"), make_product(), 1)
    order = Order.objects.create(email="a@example.com", billing=ADDRESS, shipping=ADDRESS)
    staff = client_as("staff")
    jump = staff.patch(f"/api/orders/{order.pk}/", {"status": "delivered"}, format="json")
    assert jump.status_code == 400
    total = staff.patch(f"/api/orders/{order.pk}/", {"total": "1.00"}, format="json")
    assert total.status_code == 200
    order.refresh_from_db()
    assert order.total == Decimal("0.00")  # the server's number, not the client's


def test_a_visitor_sees_active_products_and_staff_see_all(
    client_as: Any, make_product: MakeProduct
) -> None:
    on, off = make_product(name="On Sale Shelf"), make_product(name="Hidden", active=False)
    public = {row["id"] for row in client_as(None).get("/api/products/").json()["results"]}
    assert str(on.pk) in public and str(off.pk) not in public
    staff = {row["id"] for row in client_as("staff").get("/api/products/").json()["results"]}
    assert {str(on.pk), str(off.pk)} <= staff


def test_the_catalogue_filters_by_price_today_and_sorts_by_it(
    client_as: Any, make_product: MakeProduct
) -> None:
    cheap, dear = make_product(price=Decimal("5.00")), make_product(price=Decimal("50.00"))
    visitor = client_as(None)
    found = visitor.get("/api/products/", {"min_price": 10}).json()["results"]
    assert [row["id"] for row in found] == [str(dear.pk)]
    ordered = visitor.get("/api/products/", {"ordering": "-effective_price"}).json()["results"]
    assert [row["id"] for row in ordered][:2] == [str(dear.pk), str(cheap.pk)]
    assert ordered[0]["current_price"] == "50.00" and ordered[0]["available"] == 5


def test_the_catalogue_reads_in_the_same_queries_for_more_products(
    client_as: Any, make_product: MakeProduct
) -> None:
    visitor = client_as(None)

    def queries() -> int:
        with CaptureQueriesContext(connection) as captured:
            assert visitor.get("/api/products/").status_code == 200
        return len(captured)

    make_product()
    few = queries()
    for _ in range(12):
        make_product()
    assert queries() == few


def test_signing_in_claims_the_guest_orders_of_a_verified_email(
    client_as: Any, make_product: MakeProduct
) -> None:
    guest = client_as(None)
    token = put(guest, make_product(), 1).json()["token"]
    number = checkout(guest, token, email="mira@example.com").json()["number"]
    user = user_with_roles("customer")
    user.email, user.email_verified = "mira@example.com", True
    user.save()
    client_as(user=user).post("/api/carts/current/merge/", {"token": ""}, format="json")
    assert Order.objects.get(number=number).customer == user

