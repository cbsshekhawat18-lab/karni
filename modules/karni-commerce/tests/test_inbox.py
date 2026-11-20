"""Commerce's emails in the inbox (karni.notify): the buyer's confirmation and balance, the
staff's new order, and never in the inbox of an account that did not verify the address."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from django.core import mail
from karni.mail import find_kind
from karni.notify.models import Notification
from karni.testing import user_with_roles

from karni_commerce import messages, services
from tests.conftest import cart_with, pay, place
from tests.testapp.models import Gadget, Slot

pytestmark = pytest.mark.django_db

MakeGadget = Callable[..., Gadget]
MakeSlot = Callable[..., Slot]


def _account(email: str, *, verified: bool = True) -> Any:
    return user_with_roles("customer", email=email, email_verified=verified)


def _inbox(user: Any) -> list[tuple[str, str]]:
    rows = Notification.objects.filter(recipient=user).order_by("created_at")
    return [(row.kind, row.link) for row in rows]


def test_every_commerce_kind_goes_to_the_email_and_the_inbox() -> None:
    for name in messages.KINDS:
        declared = find_kind(name)
        assert declared is not None, name
        assert declared.channels == messages.CHANNELS[name] == ("email", "inbox"), name


def test_the_paid_order_reaches_the_buyers_and_the_staffs_inbox(
    make_gadget: MakeGadget, django_capture_on_commit_callbacks: Any
) -> None:
    buyer = _account("ines@example.com")
    staff = _account("orders@example.com")  # KARNI_COMMERCE_STAFF_EMAILS
    with django_capture_on_commit_callbacks(execute=True):
        order = pay(place(cart_with(("gadget", make_gadget(), 2)), "ines@example.com", buyer))
    link = services.order_link(order)
    assert _inbox(buyer) == [("commerce.order_paid", link)]
    assert _inbox(staff) == [("commerce.new_order", link)]
    paid = Notification.objects.get(recipient=buyer)
    assert paid.title == f"Order {order.number} is confirmed" and paid.read_at is None
    # the emails still go, the staff's as one email to every staff address
    kinds = sorted(message.extra_headers["X-Karni-Kind"] for message in mail.outbox)
    assert kinds == ["commerce.new_order", "commerce.order_paid"]


def test_the_balance_to_pay_reaches_the_buyers_inbox(
    make_slot: MakeSlot, django_capture_on_commit_callbacks: Any
) -> None:
    buyer = _account("ana@example.com")
    visit = make_slot(price=Decimal("50.00"), deposit=Decimal("10.00"))
    order = place(cart_with(("booking", visit, 1)), "ana@example.com", buyer, deposit=True)
    with django_capture_on_commit_callbacks(execute=True):
        order = pay(order)
    assert order.status == "part_paid"
    [balance] = Notification.objects.filter(recipient=buyer)
    assert balance.kind == "commerce.balance_due"
    assert balance.title == f"Order {order.number}: 40.00 EUR to pay"
    assert balance.link == services.order_link(order)


def test_a_guest_and_an_account_that_did_not_verify_the_address_get_email_only(
    make_gadget: MakeGadget, django_capture_on_commit_callbacks: Any
) -> None:
    claimed = _account("guest@example.com", verified=False)
    with django_capture_on_commit_callbacks(execute=True):
        pay(place(cart_with(("gadget", make_gadget(), 1)), "guest@example.com"))
    assert not Notification.objects.filter(recipient=claimed).exists()
    confirmation = [
        m for m in mail.outbox if m.extra_headers["X-Karni-Kind"] == "commerce.order_paid"
    ]
    assert [message.to for message in confirmation] == [["guest@example.com"]]


def test_a_buyer_who_turned_the_inbox_off_still_gets_the_email(
    make_gadget: MakeGadget, django_capture_on_commit_callbacks: Any
) -> None:
    from karni import notify

    buyer = _account("ines@example.com")
    notify.choose(buyer, "commerce.order_paid", inbox=False)
    with django_capture_on_commit_callbacks(execute=True):
        pay(place(cart_with(("gadget", make_gadget(), 1)), "ines@example.com", buyer))
    assert _inbox(buyer) == []
    assert any(m.to == ["ines@example.com"] for m in mail.outbox)


def test_the_new_order_email_is_a_staff_switch_never_a_buyers(buyer: Any, clerk: Any) -> None:
    from karni import notify

    assert find_kind("commerce.new_order").requires == "karni_commerce.order:view"
    assert "commerce.new_order" not in {row["kind"] for row in notify.choices(buyer)}
    assert "commerce.order_paid" in {row["kind"] for row in notify.choices(buyer)}
    assert "commerce.new_order" in {row["kind"] for row in notify.choices(clerk)}
