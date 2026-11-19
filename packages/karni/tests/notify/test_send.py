"""karni.notify: sending a kind on its channels, the switches, unsubscribes, the sender."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from django.core import mail
from django.test import override_settings
from django.utils import timezone

from karni import notify, preferences
from karni.exceptions import KarniError
from karni.mail import send_templated, silenced
from karni.notify.models import Choice, EmailTemplate, Notification, Unsubscribe
from karni.notify.services import read_token, unsubscribe_token
from karni.notify.source import NotifySource

pytestmark = pytest.mark.django_db

RECEIPT = {"order": {"number": 1001, "total": "12.00"}, "link": "/orders/1001"}


def test_a_kind_goes_to_the_email_and_the_inbox_it_declares(ana: Any, ben: Any) -> None:
    sent = notify.send("club.receipt", to=[ana, "guest@example.com"], context=RECEIPT)
    assert sent == notify.Sent(email=2, inbox=1)  # one email each: nobody sees the other
    message, other = mail.outbox
    assert (message.to, other.to) == (["ana@example.com"], ["guest@example.com"])
    assert message.subject == "Receipt 1001"
    assert message.extra_headers["X-Karni-Kind"] == "club.receipt"
    [row] = Notification.objects.all()
    assert (row.recipient, row.title, row.link) == (ana, "Receipt 1001", "/orders/1001")
    assert row.body == "Paid 12.00. /orders/1001" and row.read_at is None


def test_an_inbox_only_kind_sends_no_email_and_skips_a_guest(ana: Any) -> None:
    sent = notify.send("club.note", to=[ana, "guest@example.com"], context={"who": "Lee"})
    assert sent == notify.Sent(email=0, inbox=1)
    assert mail.outbox == []
    assert Notification.objects.get().title == "A note from Lee"


def test_an_address_reaches_the_account_with_that_email(ana: Any) -> None:
    notify.send("club.note", to="ANA@example.com", context={"who": "Lee"})
    assert Notification.objects.get().recipient == ana


def test_an_undeclared_kind_and_an_unknown_recipient_are_refused(ana: Any) -> None:
    with pytest.raises(KarniError) as undeclared:
        notify.send("club.nothing", to=[ana])
    assert undeclared.value.code == "E440"
    with pytest.raises(KarniError) as odd:
        notify.send("club.receipt", to=[42], context=RECEIPT)
    assert odd.value.code == "E443"


def test_the_project_switch_and_the_channels_hold(ana: Any) -> None:
    with preferences.override(emails={"club.receipt": False}):
        assert notify.send("club.receipt", to=[ana], context=RECEIPT) == notify.Sent()
    with override_settings(KARNI_NOTIFY_CHANNELS=["email"]):
        assert notify.send("club.receipt", to=[ana], context=RECEIPT) == notify.Sent(email=1)
    assert not Notification.objects.exists()


def test_silenced_writes_no_inbox_row_either(ana: Any) -> None:
    with silenced():
        assert notify.send("club.receipt", to=[ana], context=RECEIPT) == notify.Sent()
    assert mail.outbox == [] and not Notification.objects.exists()


def test_a_persons_own_switch_turns_one_channel_off(ana: Any, ben: Any) -> None:
    notify.choose(ana, "club.receipt", email=False)
    sent = notify.send("club.receipt", to=[ana, ben], context=RECEIPT)
    assert sent == notify.Sent(email=1, inbox=2)
    assert mail.outbox[0].to == ["ben@example.com"]
    notify.choose(ana, "club.receipt", inbox=False)
    assert notify.send("club.receipt", to=[ana], context=RECEIPT) == notify.Sent()


def test_a_kind_nobody_may_switch_ignores_the_switch(ana: Any) -> None:
    Choice.objects.create(user=ana, kind="club.code", email=False, inbox=False)
    assert notify.send("club.code", to=[ana], context={"code": "1234"}) == notify.Sent(1, 1)
    with pytest.raises(KarniError) as refused:
        notify.choose(ana, "club.code", email=False)
    assert refused.value.code == "E441"


def test_send_templated_goes_through_notify_unchanged_for_the_caller(ana: Any) -> None:
    """A part that sends with karni.mail keeps its call and gains the switches and inbox."""
    assert (
        send_templated("club/email/receipt", to=[ana.email], context=RECEIPT, kind="club.receipt")
        == 1
    )
    assert Notification.objects.get().recipient == ana
    # the caller's list stays one email to all of them, as before
    to = [ana.email, "guest@example.com"]
    assert send_templated("club/email/receipt", to=to, context=RECEIPT, kind="club.receipt") == 1
    assert sorted(mail.outbox[-1].to) == sorted(to)
    notify.choose(ana, "club.receipt", email=False)
    assert (
        send_templated("club/email/receipt", to=[ana.email], context=RECEIPT, kind="club.receipt")
        == 0
    )
    # a kind nobody declared goes by email only, as before
    assert send_templated("club/email/code", to=["x@example.com"], kind="club.other") == 1


def test_an_edited_template_wins_on_both_channels(ana: Any) -> None:
    EmailTemplate.objects.create(
        kind="club.receipt", subject="Thanks for {{ order.number }}", text="{{ order.total }}"
    )
    notify.send("club.receipt", to=[ana], context=RECEIPT)
    assert mail.outbox[0].subject == "Thanks for 1001"
    assert Notification.objects.get().title == "Thanks for 1001"


def test_the_sender_and_reply_to_come_from_the_details(ana: Any) -> None:
    preferences.save_details(
        {
            "name": "Harbour Club",
            "sender_email": "hello@club.example",
            "reply_to": "desk@club.example",
        }
    )
    notify.send("club.receipt", to=[ana], context=RECEIPT)
    [message] = mail.outbox
    assert message.from_email == "Harbour Club <hello@club.example>"
    assert message.reply_to == ["desk@club.example"]


def test_a_marketing_kind_carries_its_own_unsubscribe_link(ana: Any, ben: Any) -> None:
    assert notify.send("club.news", to=[ana, ben]).email == 2
    first, second = mail.outbox
    assert first.to == ["ana@example.com"] and second.to == ["ben@example.com"]
    link = first.extra_headers["List-Unsubscribe"].strip("<>")
    assert link.startswith("https://club.example.com/api/notify/unsubscribe/?token=")
    assert first.extra_headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert link in first.body and link not in second.body


def test_an_unsubscribed_address_gets_no_more_on_any_channel(ana: Any) -> None:
    assert notify.unsubscribe("Ana@Example.com", "club.news") is True
    assert notify.send("club.news", to=[ana, "ana@example.com"]) == notify.Sent()
    with pytest.raises(KarniError) as transactional:
        notify.unsubscribe("ana@example.com", "club.receipt")
    assert transactional.value.code == "E441"
    # turning the email on again in their own switches takes the unsubscribe back
    notify.choose(ana, "club.news", email=True)
    assert not Unsubscribe.objects.exists()
    assert notify.send("club.news", to=[ana]) == notify.Sent(email=1, inbox=1)


def test_a_guest_who_unsubscribed_is_honoured_by_send_templated() -> None:
    notify.unsubscribe("guest@example.com", "club.news")
    assert send_templated("club/email/news", to=["guest@example.com"], kind="club.news") == 0


def test_the_token_is_signed_and_names_the_address_and_kind() -> None:
    token = unsubscribe_token("Ana@Example.com", "club.news")
    assert read_token(token) == ("ana@example.com", "club.news")
    with pytest.raises(KarniError) as forged:
        read_token(token[:-2] + "xx")
    assert forged.value.code == "E442"


def test_the_inbox_helpers_and_pruning(ana: Any, ben: Any) -> None:
    for _ in range(3):
        notify.send("club.note", to=[ana, ben], context={"who": "Lee"})
    assert notify.unread_count(ana) == 3
    first = Notification.objects.filter(recipient=ana).first()
    assert first is not None
    assert notify.mark_read(ana, [first.pk]) == 1
    assert notify.mark_read(ben, [first.pk]) == 0  # not ben's
    assert notify.unread_count(ana) == 2
    assert notify.mark_read(ana) == 2 and notify.unread_count(ana) == 0
    assert notify.mark_unread(ana, [first.pk]) == 1
    old = timezone.now() - dt.timedelta(days=200)
    Notification.objects.filter(recipient=ben).update(created_at=old)
    assert notify.prune() == 3  # KARNI_NOTIFY_RETENTION_DAYS, 180 by default
    assert notify.prune(days=None) == 0
    with override_settings(KARNI_NOTIFY_RETENTION_DAYS=None):
        assert notify.prune() == 0


def test_without_the_app_the_source_sends_email_as_before(
    ana: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(NotifySource, "_installed", staticmethod(lambda: False))
    EmailTemplate.objects.create(kind="club.receipt", subject="Edited", text="Edited")
    assert NotifySource().keeps_edits() is False
    assert (
        send_templated("club/email/receipt", to=[ana.email], context=RECEIPT, kind="club.receipt")
        == 1
    )
    assert mail.outbox[0].subject == "Receipt 1001"  # the files: no edit kept without the app
    assert not Notification.objects.exists()


def test_a_family_event_sends_a_kind_once(ana: Any) -> None:
    from karni.events import Event, Registry

    bus = Registry()
    notify.on_event(
        "desk.ticket.closed",
        "club.note",
        to=lambda event: [ana],
        context=lambda event: {"who": "the desk", "text": event["ticket"]},
        registry=bus,
    )
    subscriber = bus.subscriber("karni.notify:club.note:desk.ticket.closed")
    assert subscriber is not None
    event = Event.from_payload(
        {
            "id": "3f1c1a4e-8a3b-4a43-9a51-6a3a2f1e0c11",
            "name": "desk.ticket.closed",
            "version": 1,
            "occurred_at": timezone.now().isoformat(),
            "ticket": "42",
            "minutes": 5,
        }
    )
    subscriber.func(event)
    subscriber.func(event)  # redelivered: nothing twice
    [row] = Notification.objects.all()
    assert (row.title, row.body) == ("A note from the desk", "42")


def test_people_get_the_email_and_their_account_the_inbox(ana: Any) -> None:
    from karni.people.models import Person

    Person.objects.create(email="ana@example.com", given_name="Ana", user=ana)
    Person.objects.create(email="guest@example.com", given_name="Gus")
    sent = notify.send("club.receipt", to=Person.objects.order_by("email"), context=RECEIPT)
    assert sent == notify.Sent(email=2, inbox=1)
    assert [message.to for message in mail.outbox] == [["ana@example.com"], ["guest@example.com"]]
    assert Notification.objects.get().recipient == ana
    assert notify.send("club.receipt", to=Person.objects.filter(pk=None)) == notify.Sent()


def test_a_role_is_an_audience(ana: Any, ben: Any, writer: Any) -> None:
    from karni.accounts.permissions import assign_role

    assign_role(ben, "writer")
    writer.is_active = False
    writer.save(update_fields=["is_active"])
    assert list(notify.holders("writer")) == [ben]
    sent = notify.send("club.note", to=notify.holders("writer", "customer"), context={"who": "Lee"})
    assert sent == notify.Sent(inbox=2)
    assert {row.recipient for row in Notification.objects.all()} == {ana, ben}
