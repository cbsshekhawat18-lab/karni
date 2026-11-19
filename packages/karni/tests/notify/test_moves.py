"""A move's email (``moves.<state>.notify``) through karni.notify: inbox, edits, switches."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from django.core import mail
from django.test import override_settings

from karni import notify, preferences
from karni.mail import find_kind, register_kind, unregister_kind
from karni.notify.models import EmailTemplate, Notification
from karni.rules import send_move_email
from tests.notify.conftest import person
from tests.rulesapp.models import Item, Purchase, Shop

pytestmark = pytest.mark.django_db

PAID = "rulesapp.purchase_paid"
CANCELLED = "rulesapp.purchase_cancelled"


@pytest.fixture
def purchase() -> Purchase:
    seller = person("seller@example.com")
    shop = Shop.objects.create(owner=seller, name="Corner")
    item = Item.objects.create(shop=shop, title="Lamp", price=Decimal("20.00"))
    return Purchase.objects.create(item=item, buyer=person("buyer@example.com", "customer"))


def test_a_move_email_goes_to_the_email_and_the_inbox(purchase: Purchase) -> None:
    assert send_move_email(purchase, "paid") == 1
    [message] = mail.outbox
    assert message.subject == "Paid: Lamp" and message.extra_headers["X-Karni-Kind"] == PAID
    [row] = Notification.objects.all()
    assert (row.recipient, row.kind, row.title) == (purchase.buyer, PAID, "Paid: Lamp")
    assert "We have your payment for Lamp" in row.body


def test_an_edited_move_email_and_the_recipients_switch(purchase: Purchase) -> None:
    EmailTemplate.objects.create(
        kind=CANCELLED,
        subject="{{ model }} {{ row }} is {{ state }}",
        text="Hi {{ recipient.email }}",
    )
    assert send_move_email(purchase, "cancelled") == 1
    assert mail.outbox[0].subject == f"purchase {purchase} is cancelled"
    assert mail.outbox[0].body == "Hi buyer@example.com"
    notify.choose(purchase.buyer, CANCELLED, email=False)
    assert send_move_email(purchase, "cancelled") == 0
    assert Notification.objects.filter(kind=CANCELLED).count() == 2  # the inbox still has it


def test_the_project_switch_and_the_move_channels(purchase: Purchase) -> None:
    with preferences.override(emails={CANCELLED: False}):
        assert send_move_email(purchase, "cancelled") == 0
    assert not Notification.objects.exists() and mail.outbox == []
    unregister_kind(CANCELLED)
    try:
        with override_settings(KARNI_NOTIFY_MOVE_CHANNELS=["email"]):
            from karni.notify.moves import declare_move_kinds

            declare_move_kinds()
            assert find_kind(CANCELLED).channels == ("email",)  # type: ignore[union-attr]
            assert send_move_email(purchase, "cancelled") == 1
        assert not Notification.objects.exists()
    finally:
        unregister_kind(CANCELLED)
        declare_move_kinds()


def test_an_own_subject_keeps_karnis_default_body(purchase: Purchase, club: Path) -> None:
    folder = club / "rulesapp" / "email"
    folder.mkdir(parents=True)
    (folder / "purchase_cancelled_subject.txt").write_text("Cancelled: {{ row.item.title }}")
    assert send_move_email(purchase, "cancelled") == 1
    [message] = mail.outbox
    assert message.subject == "Cancelled: Lamp"
    assert 'Your purchase "' in message.body and "is now cancelled" in message.body


def test_a_parts_own_declaration_wins(purchase: Purchase) -> None:
    own = register_kind(
        CANCELLED, title="Order called off", template="karni/email/move", fields={"row": "Row"}
    )
    try:
        from karni.notify.moves import declare_move_kinds

        declare_move_kinds()
        assert find_kind(CANCELLED) is own
    finally:
        unregister_kind(CANCELLED)
        declare_move_kinds()


def test_without_the_app_a_move_emails_as_before(
    purchase: Purchase, monkeypatch: pytest.MonkeyPatch
) -> None:
    from django.apps import apps

    installed = apps.is_installed
    monkeypatch.setattr(
        apps, "is_installed", lambda name: name != "karni.notify" and installed(name)
    )
    EmailTemplate.objects.create(kind=CANCELLED, subject="Edited", text="Edited")
    assert send_move_email(purchase, "cancelled") == 1
    assert mail.outbox[0].subject == "Your purchase is now cancelled"  # the files
    assert not Notification.objects.exists()
    assert (
        send_move_email(
            Purchase(item=purchase.item, buyer=type(purchase.buyer)(email="")), "cancelled"
        )
        == 0
    )


def test_a_move_without_a_recipient_sends_nothing(purchase: Purchase) -> None:
    nobody = Purchase(item=purchase.item, buyer=None)
    assert send_move_email(nobody, "cancelled") == 0
    assert mail.outbox == [] and not Notification.objects.exists()


def test_move_kinds_carry_their_merge_fields() -> None:
    found = find_kind(CANCELLED)
    assert found is not None and found.template == "karni/email/move"
    assert {"row", "state", "recipient.email"} <= set(found.fields)
    assert found.channels == ("email", "inbox") and found.transactional
