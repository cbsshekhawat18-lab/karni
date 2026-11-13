"""Running a shop: settings, emails a business edits, invoices, abandoned carts, reports."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.core import mail
from django.db import connection
from django.template import Context, Engine
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from karni.mail import _engine, kinds, merge_values
from rest_framework.test import APIClient

from karni_commerce import preferences_seam as preferences
from karni_commerce import reports, services
from karni_commerce.models import Cart, Coupon, EmailTemplate, Invoice, Setting
from tests.conftest import ADDRESS, cart_with, pay, place
from tests.testapp.models import Gadget

pytestmark = pytest.mark.django_db

MakeGadget = Callable[..., Gadget]


def as_user(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


# -- settings ----------------------------------------------------------------------------------


def test_a_value_reads_override_lock_saved_default_then_declared() -> None:
    assert preferences.value("commerce.guest_checkout", False) is True  # declared
    with override_settings(KARNI_PREFERENCES_DEFAULTS={"details": {"name": "Corner Shop"}}):
        assert preferences.value("details.name", "") == "Corner Shop"
        preferences.save_details({"name": "Harbour Goods"})
        assert preferences.value("details.name", "") == "Harbour Goods"
        preferences.save_details({"name": ""})  # blank: back to the default
        assert preferences.value("details.name", "") == "Corner Shop"
    preferences.save_section("commerce", {"abandoned_after_hours": 6})
    assert preferences.value("commerce.abandoned_after_hours", 1) == 6
    with override_settings(KARNI_PREFERENCES_LOCKED={"commerce": {"abandoned_after_hours": 2}}):
        assert preferences.value("commerce.abandoned_after_hours", 1) == 2
        with pytest.raises(preferences.PreferenceRefused) as locked:
            preferences.save_section("commerce", {"abandoned_after_hours": 3})
        assert locked.value.code == "E324"
        with preferences.override(commerce={"abandoned_after_hours": 9}):
            assert preferences.value("commerce.abandoned_after_hours", 1) == 9
    assert preferences.value("nobody.declared", 5) == 5
    assert preferences.value("commerce.abandoned_after_hours", "x") == "6"  # the default's type


def test_a_refused_value_says_why_and_keeps_nothing() -> None:
    with pytest.raises(preferences.PreferenceRefused) as refused:
        preferences.save_section("commerce", {"abandoned_after_hours": 0})
    assert refused.value.code == "E323" and "abandoned_after_hours" in refused.value.errors
    with pytest.raises(preferences.PreferenceRefused) as unknown:
        preferences.save_section("commerce", {"colour": "red"})
    assert unknown.value.code == "E325"
    with pytest.raises(preferences.PreferenceRefused):
        preferences.save_details({"currency": "GBP"})  # one currency per shop
    assert preferences.details().currency == "EUR"
    assert not Setting.objects.filter(group="commerce").exclude(values={}).exists()


def test_the_settings_api_for_each_role(manager: Any, clerk: Any, buyer: Any) -> None:
    assert APIClient().get("/api/preferences/").status_code in (401, 403)
    assert as_user(clerk).get("/api/preferences/").status_code == 403
    assert as_user(buyer).get("/api/preferences/").status_code == 403
    page = as_user(manager).get("/api/preferences/")
    assert page.status_code == 200, page.data
    assert page.data["details"]["can_change"] is True
    assert "currency" in page.data["details"]["locked"]
    checkout = next(row for row in page.data["sections"] if row["key"] == "commerce")
    assert checkout["values"]["guest_checkout"] is True
    assert "guest_checkout" in checkout["schema"]["properties"]
    emails = {row["name"]: row for row in page.data["emails"]["items"]}
    assert emails["commerce.order_paid"]["on"] is True
    assert emails["accounts.login_code"]["switchable"] is False
    changed = as_user(manager).patch(
        "/api/preferences/details/",
        {"name": "Harbour Goods", "sender_email": "hello@harbour.example"},
        format="json",
    )
    assert changed.status_code == 200, changed.data
    assert changed.data["values"]["name"] == "Harbour Goods"
    assert preferences.sender() == "Harbour Goods <hello@harbour.example>"
    refused = as_user(manager).patch(
        "/api/preferences/sections/commerce/", {"abandoned_after_hours": -1}, format="json"
    )
    assert refused.status_code == 400 and "abandoned_after_hours" in refused.data["errors"]
    assert (
        as_user(manager)
        .patch("/api/preferences/sections/nope/", {"x": 1}, format="json")
        .status_code
        == 404
    )
    off = as_user(manager).patch(
        "/api/preferences/emails/commerce.order_paid/", {"on": False}, format="json"
    )
    assert off.data == {"name": "commerce.order_paid", "on": False}
    always = as_user(manager).patch(
        "/api/preferences/emails/accounts.login_code/", {"on": False}, format="json"
    )
    assert always.status_code == 400
    assert (
        as_user(clerk).patch("/api/preferences/details/", {"name": "X"}, format="json").status_code
        == 403
    )
    public = APIClient().get("/api/preferences/public/")
    assert public.data["name"] == "Harbour Goods" and "sender_email" not in public.data


def test_switched_off_emails_and_the_sender_follow_the_settings(
    make_gadget: MakeGadget, django_capture_on_commit_callbacks: Any
) -> None:
    preferences.save_details({"name": "Harbour Goods", "sender_email": "hello@harbour.example"})
    preferences.switch("email", "commerce.new_order", False)
    with django_capture_on_commit_callbacks(execute=True):
        pay(place(cart_with(("gadget", make_gadget(), 1))))
    kinds_sent = [message.extra_headers["X-Karni-Kind"] for message in mail.outbox]
    assert kinds_sent == ["commerce.order_paid"]
    assert mail.outbox[0].from_email == "Harbour Goods <hello@harbour.example>"
    assert "Harbour Goods" in mail.outbox[0].subject


def test_staff_emails_come_from_the_checkout_settings(
    make_gadget: MakeGadget, django_capture_on_commit_callbacks: Any
) -> None:
    preferences.save_section("commerce", {"staff_emails": "a@shop.example, b@shop.example"})
    with django_capture_on_commit_callbacks(execute=True):
        pay(place(cart_with(("gadget", make_gadget(), 1))))
    [staff] = [m for m in mail.outbox if m.extra_headers["X-Karni-Kind"] == "commerce.new_order"]
    assert staff.to == ["a@shop.example", "b@shop.example"]


def test_checkout_follows_the_guest_and_terms_settings(
    api: APIClient, buyer: Any, make_gadget: MakeGadget
) -> None:
    lamp = make_gadget()
    token = api.post(
        "/api/carts/current/lines/", {"kind": "gadget", "item": str(lamp.pk), "quantity": 1}
    ).data["token"]
    body = {"email": "g@example.com", "billing": ADDRESS}
    preferences.save_section("commerce", {"guest_checkout": False, "accept_terms": True})
    cart = api.get("/api/carts/current/", HTTP_X_CART_TOKEN=token).data
    assert cart["checkout"] == {
        "guest_checkout": False,
        "accept_terms": True,
        "terms_url": "/terms",
    }
    guest = api.post("/api/carts/current/checkout/", body, format="json", HTTP_X_CART_TOKEN=token)
    assert guest.status_code == 403
    signed = as_user(buyer)
    signed.post(
        "/api/carts/current/lines/",
        {"kind": "gadget", "item": str(lamp.pk), "quantity": 1},
        format="json",
    )
    refused = signed.post("/api/carts/current/checkout/", body, format="json")
    assert refused.status_code == 400 and "accept_terms" in refused.data
    placed = signed.post(
        "/api/carts/current/checkout/", {**body, "accept_terms": True}, format="json"
    )
    assert placed.status_code == 201, placed.data


# -- emails a business edits -------------------------------------------------------------------


def test_every_commerce_email_file_is_an_editable_template_on_its_merge_fields(
    make_gadget: MakeGadget,
) -> None:
    """The files are what the editor starts from: each renders the same with the
    restricted engine and the declared merge fields only."""
    order = pay(place(cart_with(("gadget", make_gadget(), 2))))
    from karni_commerce.messages import business
    from karni_commerce.services import order_link

    context = {
        "business": business(),
        "order": order,
        "lines": list(order.lines.all()),
        "link": order_link(order),
        "refund": {"amount": Decimal("3.00")},
        "note": {"body": "Thanks"},
    }
    from django.template.loader import render_to_string

    declared = [kind for kind in kinds() if kind.name.startswith("commerce.")]
    assert len(declared) == 6
    for kind in declared:
        values = merge_values(kind.fields, context)
        for part in ("subject", "body"):
            from karni_commerce.email_templates import file_source

            source = file_source(kind.template, part)
            assert source, kind.name
            restricted = _engine().from_string(source).render(Context(values))
            full = render_to_string(f"{kind.template}_{part}.txt", context)
            assert restricted == full, kind.name
    assert isinstance(_engine(), Engine)


def test_the_email_editor_api(
    manager: Any, clerk: Any, make_gadget: MakeGadget, django_capture_on_commit_callbacks: Any
) -> None:
    rows = as_user(manager).get("/api/email-templates/")
    assert rows.status_code == 200
    paid = next(row for row in rows.data if row["kind"] == "commerce.order_paid")
    assert paid["edited"] is False and "{{ order.number }}" in paid["subject"]
    assert {"name": "order.number", "meaning": "The order's number"} in paid["fields"]
    assert as_user(clerk).get("/api/email-templates/").status_code == 403
    bad = as_user(manager).put(
        "/api/email-templates/commerce.order_paid/",
        {"subject": "Hi", "text": "{% load static %}"},
        format="json",
    )
    assert bad.status_code == 400 and "text" in bad.data
    preview = as_user(manager).post(
        "/api/email-templates/commerce.order_paid/preview/",
        {
            "subject": "Order {{ order.number }}",
            "text": "{% for line in lines %}{{ line.name }};{% endfor %}",
        },
        format="json",
    )
    assert preview.data["subject"] == "Order [order.number]"
    assert preview.data["text"] == "[lines.name];[lines.name];"
    saved = as_user(manager).put(
        "/api/email-templates/commerce.order_paid/",
        {"subject": "Thank you for order {{ order.number }}", "text": "Total {{ order.total }}"},
        format="json",
    )
    assert saved.status_code == 200 and saved.data["edited"] is True
    with django_capture_on_commit_callbacks(execute=True):
        order = pay(place(cart_with(("gadget", make_gadget(price=Decimal("12.00")), 1))))
    [confirmation] = [
        m for m in mail.outbox if m.extra_headers["X-Karni-Kind"] == "commerce.order_paid"
    ]
    assert confirmation.subject == f"Thank you for order {order.number}"
    assert confirmation.body == "Total 12.00"
    back = as_user(manager).delete("/api/email-templates/commerce.order_paid/")
    assert back.data["edited"] is False and not EmailTemplate.objects.exists()
    assert as_user(manager).get("/api/email-templates/nope.kind/").status_code == 404


# -- invoices ----------------------------------------------------------------------------------


def test_a_paid_order_gets_an_invoice_numbered_in_turn(
    buyer: Any, clerk: Any, make_gadget: MakeGadget
) -> None:
    preferences.save_details(
        {"name": "Harbour Goods", "address": "1 Quay\nPorto", "tax_number": "PT123"}
    )
    preferences.save_section("commerce", {"invoice_prefix": "HG-", "invoice_footer": "Bank: 123"})
    waiting = place(cart_with(("gadget", make_gadget(), 1)), email=buyer.email, user=buyer)
    assert not Invoice.objects.exists()
    first = pay(waiting)
    second = pay(place(cart_with(("gadget", make_gadget(), 2))))
    assert [(i.order_id, i.number, i.reference) for i in Invoice.objects.order_by("number")] == [
        (first.pk, 1001, "HG-1001"),
        (second.pk, 1002, "HG-1002"),
    ]
    assert services.issue_invoice(first).number == 1001  # once
    preferences.save_details({"name": "Renamed"})
    assert Invoice.objects.get(order=first).seller["tax_number"] == "PT123"
    page = as_user(buyer).get("/api/orders/document/", {"number": first.number})
    assert page.status_code == 200 and page["Content-Type"].startswith("text/html")
    html = page.content.decode()
    assert "HG-1001" in html and "PT123" in html and "Bank: 123" in html
    assert (
        as_user(buyer).get("/api/orders/lookup/", {"number": first.number}).data["invoice"]
        == "HG-1001"
    )
    guest = APIClient().get("/api/orders/document/", {"number": second.number, "key": second.key})
    assert guest.status_code == 200
    stranger = APIClient().get("/api/orders/document/", {"number": second.number, "key": "x"})
    assert stranger.status_code == 404
    slip = as_user(clerk).get(
        "/api/orders/document/", {"number": first.number, "kind": "packing_slip"}
    )
    assert slip.status_code == 200 and "Packing slip" in slip.content.decode()
    assert "12.00" not in slip.content.decode()  # no prices on a packing slip
    no_slip = as_user(buyer).get(
        "/api/orders/document/", {"number": first.number, "kind": "packing_slip"}
    )
    assert no_slip.status_code == 404


# -- abandoned carts ---------------------------------------------------------------------------


def test_abandoned_carts_for_staff(
    api: APIClient, clerk: Any, buyer: Any, make_gadget: MakeGadget
) -> None:
    lamp = make_gadget(name="Desk Lamp", price=Decimal("20.00"))
    old = timezone.now() - timedelta(hours=3)
    carts = []
    for number in range(4):
        cart = cart_with(("gadget", lamp, number + 1))
        Cart.objects.filter(pk=cart.pk).update(touched_at=old, email=f"v{number}@example.com")
        carts.append(cart)
    fresh = cart_with(("gadget", lamp, 1))  # touched now: not abandoned yet
    checked_out = cart_with(("gadget", lamp, 1))
    Cart.objects.filter(pk=checked_out.pk).update(touched_at=old)
    place(checked_out)  # its lines went into the order
    assert as_user(buyer).get("/api/carts/abandoned/").status_code == 403
    with CaptureQueriesContext(connection) as queries:
        answer = as_user(clerk).get("/api/carts/abandoned/")
    assert answer.status_code == 200, answer.data
    rows = answer.data["results"]
    assert {row["id"] for row in rows} == {str(cart.pk) for cart in carts}
    assert str(fresh.pk) not in {row["id"] for row in rows}
    biggest = next(row for row in rows if row["email"] == "v3@example.com")
    assert (biggest["items"], biggest["value"], biggest["lines"]) == (4, "80.00", ["4 x Desk Lamp"])
    assert len(queries) <= 12, [q["sql"] for q in queries.captured_queries]
    found = as_user(clerk).get("/api/carts/abandoned/", {"search": "v2@"})
    assert [row["email"] for row in found.data["results"]] == ["v2@example.com"]
    preferences.save_section("commerce", {"abandoned_after_hours": 5})
    assert as_user(clerk).get("/api/carts/abandoned/").data["results"] == []


def test_the_quote_keeps_the_email_a_visitor_typed(api: APIClient, make_gadget: MakeGadget) -> None:
    lamp = make_gadget()
    token = api.post(
        "/api/carts/current/lines/", {"kind": "gadget", "item": str(lamp.pk), "quantity": 1}
    ).data["token"]
    api.post(
        "/api/carts/current/quote/",
        {"address": {"country": "FR"}, "email": "mira@example.com"},
        format="json",
        HTTP_X_CART_TOKEN=token,
    )
    assert Cart.objects.get(token=token).email == "mira@example.com"


# -- reports -----------------------------------------------------------------------------------


def test_sales_reports_add_up_and_export(manager: Any, buyer: Any, make_gadget: MakeGadget) -> None:
    Coupon.objects.create(code="TEN", kind="percent", amount=Decimal("10"))
    lamp = make_gadget(name="Desk Lamp", price=Decimal("20.00"), stock=20)
    mug = make_gadget(name="Mug", price=Decimal("5.00"), stock=20)
    pay(place(cart_with(("gadget", lamp, 2), ("gadget", mug, 1))))
    coupon_cart = cart_with(("gadget", mug, 2))
    services.apply_coupon(coupon_cart, "TEN")
    pay(services.checkout(coupon_cart, email="c@example.com", billing=ADDRESS))
    place(cart_with(("gadget", lamp, 1)))  # not paid: not counted
    client = as_user(manager)
    listed = [row["key"] for row in client.get("/api/orders/reports/").data]
    assert listed[:3] == ["commerce.sales_by_date", "commerce.sales_by_item", "commerce.coupons"]
    assert as_user(buyer).get("/api/orders/reports/").data == []
    assert as_user(buyer).get("/api/orders/reports/commerce.sales_by_date/").status_code == 404
    by_date = client.get("/api/orders/reports/commerce.sales_by_date/").data
    assert by_date["totals"]["orders"] == 2
    assert by_date["totals"]["gross"] == "55.00"
    assert by_date["totals"]["discounts"] == "1.00"
    assert by_date["totals"]["net"] == "54.00"
    by_item = client.get("/api/orders/reports/commerce.sales_by_item/").data
    assert [(row["name"], row["sold"], row["gross"]) for row in by_item["rows"]] == [
        ("Desk Lamp", 2, "40.00"),
        ("Mug", 3, "15.00"),
    ]
    coupons = client.get("/api/orders/reports/commerce.coupons/").data
    assert [(row["code"], row["uses"], row["discount"]) for row in coupons["rows"]] == [
        ("TEN", 1, "1.00")
    ]
    csv = client.get("/api/orders/reports/commerce.sales_by_item/", {"export": "csv"})
    assert csv["Content-Type"] == "text/csv"
    assert "attachment" in csv["Content-Disposition"]
    lines = csv.content.decode().splitlines()
    assert lines[0] == "Item,Kind,Sold,Refunded,Sales,Discounts,Net"
    assert lines[-1].startswith("Total,")
    before = client.get(
        "/api/orders/reports/commerce.sales_by_date/",
        {"start": "2020-01-01", "end": "2020-01-31", "by": "month"},
    ).data
    assert before["rows"] == [] and before["by"] == "month"
    wrong = client.get(
        "/api/orders/reports/commerce.sales_by_date/", {"start": "2026-02-01", "end": "2026-01-01"}
    )
    assert wrong.status_code == 400


def test_a_csv_cell_never_runs_as_a_formula() -> None:
    answer = {
        "columns": [{"key": "name", "label": "Name"}, {"key": "n", "label": "N"}],
        "rows": [{"name": "=HYPERLINK(1)", "n": "-3.50"}],
        "totals": {},
    }
    assert reports.as_csv(answer).splitlines()[1] == "'=HYPERLINK(1),-3.50"
