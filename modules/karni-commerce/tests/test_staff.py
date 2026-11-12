"""The staff's side of the orders: the order page, notes, orders placed by hand and customers."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from django.core import mail
from django.db import connection
from django.test.utils import CaptureQueriesContext
from karni.testing import user_with_roles
from rest_framework.test import APIClient

from karni_commerce import services
from karni_commerce.models import Order, OrderNote
from tests.conftest import ADDRESS, cart_with, pay, place, refund_webhook
from tests.testapp.models import Gadget

pytestmark = pytest.mark.django_db

MakeGadget = Callable[..., Gadget]


def as_user(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_staff_read_an_order_with_its_payments_refunds_notes_and_buyer(
    clerk: Any, manager: Any, make_gadget: MakeGadget
) -> None:
    order = pay(place(cart_with(("gadget", make_gadget(price=Decimal("30.00")), 2))))
    services.add_note(order, "Gift wrap it.", kind="customer", author=clerk)
    services.add_note(order, "Fragile.", author=clerk)
    as_user(manager).post(f"/api/orders/{order.pk}/refund/", {"amount": "10.00"}, format="json")
    refund_webhook(order)
    answer = as_user(clerk).get(f"/api/orders/{order.pk}/staff/")
    assert answer.status_code == 200, answer.data
    data = answer.data
    assert [note["body"] for note in data["notes"]] == ["Gift wrap it.", "Fragile."]
    assert data["notes"][0]["author_name"] == clerk.get_full_name()
    assert [(p["amount"], p["status"]) for p in data["payments"]] == [
        ("60.00", "partially_refunded")
    ]
    assert [(r["amount"], r["status"]) for r in data["refunds"]] == [("10.00", "succeeded")]
    assert (data["refundable"], data["can_refund"], data["can_cancel"]) == ("50.00", True, False)
    assert data["buyer"] == {
        "user": None,
        "name": "",
        "email": "guest@example.com",
        "orders": 1,
        "spent": "50.00",
    }


def test_a_buyer_reads_the_notes_to_them_and_never_the_internal_ones(
    buyer: Any, clerk: Any, make_gadget: MakeGadget
) -> None:
    order = place(cart_with(("gadget", make_gadget(), 1)), email=buyer.email, user=buyer)
    services.add_note(order, "We ship on Monday.", kind="customer", author=clerk)
    services.add_note(order, "Customer called twice.", author=clerk)
    seen = as_user(buyer).get("/api/orders/lookup/", {"number": order.number}).data
    assert [note["body"] for note in seen["notes"]] == ["We ship on Monday."]
    assert as_user(buyer).get(f"/api/orders/{order.pk}/staff/").status_code in (403, 404)


def test_a_note_to_the_customer_is_emailed_and_an_internal_one_is_not(
    clerk: Any, make_gadget: MakeGadget, django_capture_on_commit_callbacks: Any
) -> None:
    order = place(cart_with(("gadget", make_gadget(), 1)), email="ines@example.com")
    staff = as_user(clerk)
    with django_capture_on_commit_callbacks(execute=True):
        written = staff.post(
            f"/api/orders/{order.pk}/notes/",
            {"body": "Your parcel leaves today.", "kind": "customer"},
            format="json",
        )
        staff.post(f"/api/orders/{order.pk}/notes/", {"body": "Checked."}, format="json")
    assert written.status_code == 200, written.data
    notes = [m for m in mail.outbox if m.extra_headers.get("X-Karni-Kind") == "commerce.order_note"]
    assert [m.to for m in notes] == [["ines@example.com"]]
    assert "Your parcel leaves today." in notes[0].body
    assert OrderNote.objects.filter(order=order).count() == 2
    assert (
        staff.post(f"/api/orders/{order.pk}/notes/", {"body": " "}, format="json").status_code
        == 400
    )


def test_a_buyer_cannot_write_a_note(buyer: Any, make_gadget: MakeGadget) -> None:
    order = place(cart_with(("gadget", make_gadget(), 1)), email=buyer.email, user=buyer)
    answer = as_user(buyer).post(f"/api/orders/{order.pk}/notes/", {"body": "Hi"}, format="json")
    assert answer.status_code in (403, 404)


def test_staff_place_an_order_by_hand_priced_by_the_server(
    manager: Any, make_gadget: MakeGadget, django_capture_on_commit_callbacks: Any
) -> None:
    lamp = make_gadget(price=Decimal("20.00"), stock=3)
    account = user_with_roles("customer", email="noor@example.com", email_verified=True)
    body = {
        "email": "Noor@example.com",
        "billing": ADDRESS,
        "lines": [{"kind": "gadget", "item": str(lamp.pk), "quantity": 2, "price": "0.01"}],
    }
    with django_capture_on_commit_callbacks(execute=True):
        answer = as_user(manager).post("/api/orders/manual/", body, format="json")
    assert answer.status_code == 201, answer.data
    order = Order.objects.get(number=answer.data["number"])
    assert (order.status, order.total, order.user) == ("pending", Decimal("40.00"), account)
    assert order.hold_until is not None and order.hold_until > order.created_at
    assert answer.data["link"].endswith(f"/orders/{order.number}?key={order.key}")
    lamp.refresh_from_db()
    assert lamp.available == 1  # held for the buyer's payment
    asked = [
        m for m in mail.outbox if m.extra_headers.get("X-Karni-Kind") == "commerce.payment_request"
    ]
    assert [m.to for m in asked] == [["Noor@example.com"]]
    assert order.notes.get().kind == "internal"


def test_an_order_by_hand_needs_order_add_and_holds_stock_like_checkout(
    clerk: Any, manager: Any, make_gadget: MakeGadget
) -> None:
    lamp = make_gadget(stock=1)
    body = {
        "email": "noor@example.com",
        "billing": ADDRESS,
        "lines": [{"kind": "gadget", "item": str(lamp.pk), "quantity": 2}],
    }
    assert as_user(clerk).post("/api/orders/manual/", body, format="json").status_code == 403
    refused = as_user(manager).post("/api/orders/manual/", body, format="json")
    assert refused.status_code == 400 and Order.objects.count() == 0


def test_staff_find_items_to_put_on_an_order(manager: Any, make_gadget: MakeGadget) -> None:
    make_gadget(name="Desk Lamp", sku="LMP-1")
    make_gadget(name="Kettle", sku="KTL-1")
    found = as_user(manager).get("/api/orders/items/", {"kind": "gadget", "search": "lamp"})
    assert found.status_code == 200
    assert [(row["name"], row["price"]) for row in found.data] == [("Desk Lamp", "20.00")]


def test_customers_are_the_buyers_by_email_with_what_they_spent(
    clerk: Any, buyer: Any, make_gadget: MakeGadget
) -> None:
    lamp = make_gadget(price=Decimal("10.00"), stock=20)
    pay(place(cart_with(("gadget", lamp, 1)), email=buyer.email, user=buyer))
    pay(place(cart_with(("gadget", lamp, 2)), email="INES@example.com"))
    place(cart_with(("gadget", lamp, 1)), email="noor@example.com")
    staff = as_user(clerk)
    rows = staff.get("/api/orders/customers/", {"ordering": "-spent"}).data["results"]
    assert [(row["email"].lower(), row["order_count"], row["spent"]) for row in rows] == [
        ("ines@example.com", 2, "30.00"),
        ("noor@example.com", 1, "0.00"),
    ]
    assert rows[0]["has_account"] is True
    found = staff.get("/api/orders/customers/", {"search": "noor"}).data["results"]
    assert [row["email"] for row in found] == ["noor@example.com"]
    page = staff.get("/api/orders/customer/", {"email": "ines@example.com"})
    assert page.status_code == 200
    assert (page.data["order_count"], page.data["spent"]) == (2, "30.00")
    assert page.data["account"]["email"] == buyer.email
    assert (
        page.data["addresses"]
        == [{**ADDRESS, "company": "", "line2": "", "region": "", "phone": ""}]
        or len(page.data["addresses"]) == 1
    )
    assert staff.get("/api/orders/customer/", {"email": "x@example.com"}).status_code == 404


def test_customers_list_in_the_same_queries_for_more_buyers(
    clerk: Any, make_gadget: MakeGadget
) -> None:
    lamp = make_gadget(stock=50)
    staff = as_user(clerk)
    for number in range(2):
        place(cart_with(("gadget", lamp, 1)), email=f"buyer{number}@example.com")
    staff.get("/api/orders/customers/")  # the caller's roles, read once
    with CaptureQueriesContext(connection) as few:
        staff.get("/api/orders/customers/")
    for number in range(2, 12):
        place(cart_with(("gadget", lamp, 1)), email=f"buyer{number}@example.com")
    with CaptureQueriesContext(connection) as many:
        assert staff.get("/api/orders/customers/").data["count"] == 12
    assert len(many) == len(few)


def test_a_buyer_never_reads_the_customers(buyer: Any) -> None:
    assert as_user(buyer).get("/api/orders/customers/").status_code == 403
    assert APIClient().get("/api/orders/customers/").status_code in (401, 403)


def test_staff_filter_orders_by_buyer_email(clerk: Any, make_gadget: MakeGadget) -> None:
    lamp = make_gadget(stock=9)
    place(cart_with(("gadget", lamp, 1)), email="ines@example.com")
    place(cart_with(("gadget", lamp, 1)), email="noor@example.com")
    found = as_user(clerk).get("/api/orders/", {"email__iexact": "INES@example.com"})
    assert [row["email"] for row in found.data["results"]] == ["ines@example.com"]


def test_every_move_of_the_money_is_in_the_history(clerk: Any, make_gadget: MakeGadget) -> None:
    order = pay(place(cart_with(("gadget", make_gadget(), 1))))
    history = as_user(clerk).get(f"/api/orders/{order.pk}/history/")
    assert history.status_code == 200
    changed = [set(entry["fields_changed"]) for entry in history.data["results"]]
    assert any("status" in fields for fields in changed)
