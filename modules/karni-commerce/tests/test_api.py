"""The commerce API per role: a visitor, a buyer, another buyer, a clerk and a manager."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from karni_commerce.models import Order
from tests.conftest import ADDRESS, cart_with, pay, place
from tests.testapp.models import Gadget

pytestmark = pytest.mark.django_db

LINES = "/api/carts/current/lines/"
CHECKOUT = "/api/carts/current/checkout/"


def put(
    api: APIClient, gadget: Gadget, quantity: int, token: str | None = None, **more: Any
) -> Any:
    headers = {"HTTP_X_CART_TOKEN": token} if token else {}
    body = {"kind": "gadget", "item": str(gadget.pk), "quantity": quantity, **more}
    return api.post(LINES, body, format="json", **headers)


def test_a_visitor_fills_a_cart_by_its_token_and_checks_out(
    api: APIClient, make_gadget: Callable[..., Gadget]
) -> None:
    lamp = make_gadget(stock=4, price=Decimal("20.00"), sale_price=Decimal("16.00"))
    answer = put(api, lamp, 2)
    assert answer.status_code == 200, answer.data
    token = answer.data["token"]
    assert token and answer.data["count"] == 2 and answer.data["subtotal"] == "32.00"
    [line] = answer.data["lines"]
    assert (line["name"], line["unit_price"], line["compare_at_price"]) == (
        "Lamp",
        "16.00",
        "20.00",
    )
    assert line["url"] == f"/gadgets/{lamp.pk}" and answer.data["currency"] == "EUR"
    assert put(api, lamp, 1, token, add=True).data["count"] == 3
    assert api.get("/api/carts/current/").data["count"] == 0  # no token: no cart
    placed = api.post(
        CHECKOUT,
        {"email": "guest@example.com", "billing": ADDRESS},
        format="json",
        HTTP_X_CART_TOKEN=token,
    )
    assert placed.status_code == 201, placed.data
    assert placed.data["url"].startswith("https://checkout.test/pay/")
    order = Order.objects.get(number=placed.data["number"])
    assert order.total == Decimal("48.00") and order.user is None
    looked = api.get("/api/orders/lookup/", {"number": order.number, "key": placed.data["key"]})
    assert looked.status_code == 200 and looked.data["payable"] is True
    assert looked.data["lines"][0]["line_total"] == "48.00"
    assert api.get("/api/orders/lookup/", {"number": order.number}).status_code == 404
    assert api.get("/api/orders/").status_code in (401, 403)


def test_checkout_never_takes_a_price_from_the_client(
    api: APIClient, make_gadget: Callable[..., Gadget]
) -> None:
    lamp = make_gadget(price=Decimal("20.00"))
    token = put(api, lamp, 1).data["token"]
    body = {"email": "g@example.com", "billing": ADDRESS, "total": "0.01", "price": "0.01"}
    placed = api.post(CHECKOUT, body, format="json", HTTP_X_CART_TOKEN=token)
    assert Order.objects.get(number=placed.data["number"]).total == Decimal("20.00")


def test_a_refused_line_and_an_empty_checkout_answer_400(
    api: APIClient, make_gadget: Callable[..., Gadget]
) -> None:
    lamp = make_gadget(stock=1)
    assert put(api, lamp, 2).status_code == 400
    empty = api.post(CHECKOUT, {"email": "g@example.com", "billing": ADDRESS}, format="json")
    assert empty.status_code == 400


def test_a_buyer_reads_their_own_orders_and_never_anothers(
    api: APIClient, make_gadget: Callable[..., Gadget], buyer: Any, other: Any
) -> None:
    mine = place(cart_with(("gadget", make_gadget(), 1)), email=buyer.email, user=buyer)
    theirs = place(cart_with(("gadget", make_gadget(), 1)), email=other.email, user=other)
    api.force_authenticate(buyer)
    listed = api.get("/api/orders/")
    assert listed.status_code == 200
    assert [row["number"] for row in listed.data["results"]] == [mine.number]
    assert api.get(f"/api/orders/{theirs.pk}/").status_code == 404
    assert api.get("/api/orders/lookup/", {"number": theirs.number}).status_code == 404
    assert api.get("/api/orders/lookup/", {"number": mine.number}).status_code == 200
    lines = api.get("/api/order-lines/")
    assert {str(row["order"]) for row in lines.data["results"]} == {str(mine.pk)}
    assert api.post(f"/api/orders/{mine.pk}/cancel/").status_code in (403, 404)
    assert api.patch(f"/api/orders/{mine.pk}/", {"note": "x"}, format="json").status_code in (
        403,
        405,
    )


def test_a_signed_in_buyers_checkout_carries_their_account(
    api: APIClient, make_gadget: Callable[..., Gadget], buyer: Any
) -> None:
    api.force_authenticate(buyer)
    assert put(api, make_gadget(), 1).data["token"] is None  # a person's cart needs no token
    placed = api.post(CHECKOUT, {"billing": ADDRESS}, format="json")
    assert placed.status_code == 201, placed.data
    order = Order.objects.get(number=placed.data["number"])
    assert (order.user, order.email, order.name) == (
        buyer,
        buyer.email,
        buyer.get_full_name() or "Ines Moreau",
    )


def test_merge_joins_the_visitors_cart_after_sign_in(
    api: APIClient, make_gadget: Callable[..., Gadget], buyer: Any
) -> None:
    lamp = make_gadget(stock=5)
    token = put(api, lamp, 2).data["token"]
    api.force_authenticate(buyer)
    merged = api.post("/api/carts/current/merge/", {"token": token}, format="json")
    assert merged.status_code == 200 and merged.data["count"] == 2


def test_a_clerk_reads_every_order_and_cancels_but_cannot_refund(
    api: APIClient, make_gadget: Callable[..., Gadget], clerk: Any, buyer: Any
) -> None:
    order = pay(place(cart_with(("gadget", make_gadget(), 1)), user=buyer, email=buyer.email))
    api.force_authenticate(clerk)
    assert api.get("/api/orders/").data["count"] == 1
    assert api.get("/api/orders/lookup/", {"number": order.number}).status_code == 200
    refused = api.post(f"/api/orders/{order.pk}/refund/", {"amount": "5.00"}, format="json")
    assert refused.status_code == 403
    cancelled = api.post(f"/api/orders/{order.pk}/cancel/", {"reason": "duplicate"}, format="json")
    assert cancelled.status_code == 200, cancelled.data
    assert cancelled.data["status"] == "cancelled"


def test_a_manager_refunds_by_amount(
    api: APIClient, make_gadget: Callable[..., Gadget], manager: Any
) -> None:
    order = pay(place(cart_with(("gadget", make_gadget(price=Decimal("20.00")), 1))))
    api.force_authenticate(manager)
    answer = api.post(f"/api/orders/{order.pk}/refund/", {"amount": "5.00"}, format="json")
    assert answer.status_code == 200, answer.data
    assert order.refunds.get().amount == Decimal("5.00")
    too_much = api.post(f"/api/orders/{order.pk}/refund/", {"amount": "50.00"}, format="json")
    assert too_much.status_code == 400


def test_pay_starts_the_payment_again_for_the_guest_with_the_key(
    api: APIClient, make_gadget: Callable[..., Gadget]
) -> None:
    order = pay(place(cart_with(("gadget", make_gadget(), 1))), "decline")
    assert api.post("/api/orders/pay/", {"number": order.number}, format="json").status_code == 404
    again = api.post("/api/orders/pay/", {"number": order.number, "key": order.key}, format="json")
    assert again.status_code == 200 and again.data["url"]


def test_the_cart_reads_its_items_in_a_few_queries(
    api: APIClient, make_gadget: Callable[..., Gadget]
) -> None:
    token = put(api, make_gadget(), 1).data["token"]
    for number in range(9):
        put(api, make_gadget(name=f"Item {number}"), 1, token)
    with CaptureQueriesContext(connection) as queries:
        answer = api.get("/api/carts/current/", HTTP_X_CART_TOKEN=token)
    assert answer.data["count"] == 10
    assert len(queries) <= 6, [query["sql"] for query in queries.captured_queries]


def test_the_orders_list_is_not_n_plus_one(
    api: APIClient, make_gadget: Callable[..., Gadget], clerk: Any
) -> None:
    for _ in range(3):
        place(cart_with(("gadget", make_gadget(), 1)))
    api.force_authenticate(clerk)
    with CaptureQueriesContext(connection) as few:
        api.get("/api/orders/")
    for _ in range(7):
        place(cart_with(("gadget", make_gadget(), 1)))
    with CaptureQueriesContext(connection) as many:
        answer = api.get("/api/orders/")
    assert answer.data["count"] == 10
    assert len(many) <= len(few)


def test_mine_lists_only_the_persons_own_orders_even_for_staff(
    api: APIClient, make_gadget: Callable[..., Gadget], clerk: Any
) -> None:
    place(cart_with(("gadget", make_gadget(), 1)))
    own = place(cart_with(("gadget", make_gadget(), 1)), user=clerk, email=clerk.email)
    api.force_authenticate(clerk)
    assert api.get("/api/orders/").data["count"] == 2
    mine = api.get("/api/orders/", {"mine": "true"}).data["results"]
    assert [row["number"] for row in mine] == [own.number]
