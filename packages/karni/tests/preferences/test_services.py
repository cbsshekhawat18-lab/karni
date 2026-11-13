"""Preferences read and changed in code: one call with a typed default, locks, audit, switches."""

from __future__ import annotations

from typing import Any

import pytest
from django.test import override_settings

from karni import preferences
from karni.audit.models import ChangeLog
from karni.errorcodes import KarniError
from karni.preferences.models import Details, SectionValue, Switch
from karni.preferences.registry import find_section
from tests.helpdeskapp.preferences import HelpdeskPreferences

pytestmark = pytest.mark.django_db


def _code(exc: pytest.ExceptionInfo[KarniError]) -> str | None:
    return exc.value.code


# reading


def test_a_value_reads_its_declared_default_as_the_default_type() -> None:
    assert preferences.value("helpdeskapp.reply_within_hours", 0) == 24
    assert preferences.value("helpdeskapp.greeting", "") == "Hello"
    section = preferences.get(HelpdeskPreferences)
    assert isinstance(section, HelpdeskPreferences) and section.priority == "normal"
    assert preferences.get("helpdeskapp").model_dump() == section.model_dump()


def test_an_unknown_section_or_field_returns_the_default_given() -> None:
    assert preferences.value("shop.max_items", 7) == 7  # a part not installed
    assert preferences.value("helpdeskapp.nothing", "x") == "x"
    assert preferences.value("details.nothing", 3) == 3
    with pytest.raises(KarniError) as exc:
        preferences.value("helpdeskapp", 1)
    assert _code(exc) == "E325"
    with pytest.raises(KarniError) as exc:
        preferences.get("shop")
    assert _code(exc) == "E325"


def test_a_value_of_another_type_is_read_as_the_default_type() -> None:
    preferences.save_section("helpdeskapp", {"reply_within_hours": 12})
    assert preferences.value("helpdeskapp.reply_within_hours", 0.0) == 12.0
    assert preferences.value("helpdeskapp.greeting", 0) == 0  # "Hello" is no int: the default
    preferences.save_section("helpdeskapp", {"greeting": "12"})
    assert preferences.value("helpdeskapp.greeting", 0) == 12


def test_details_fall_back_to_the_deployment_and_django() -> None:
    found = preferences.details()
    assert found.time_zone and found.language and found.currency_display == "symbol"
    assert found.name == ""
    with override_settings(KARNI_PREFERENCES_DEFAULTS={"details": {"name": "Harbour Yoga"}}):
        assert preferences.value("details.name", "") == "Harbour Yoga"
        assert preferences.details().sender_name == "Harbour Yoga"  # the name, until set
        preferences.save_details({"name": "Harbour Yoga Studio"})
        assert preferences.value("details.name", "") == "Harbour Yoga Studio"
        preferences.save_details({"name": ""})  # blank: the default again
        assert preferences.value("details.name", "") == "Harbour Yoga"


def test_the_sender_is_the_details_name_and_address() -> None:
    assert preferences.sender() is None
    preferences.save_details({"name": "Harbour Yoga", "sender_email": "hello@harbour.example"})
    assert preferences.sender() == "Harbour Yoga <hello@harbour.example>"


# changing


def test_a_section_change_is_validated_stored_and_reset_with_none(admin: Any) -> None:
    found = preferences.save_section("helpdeskapp", {"reply_within_hours": 4}, user=admin)
    assert found.reply_within_hours == 4  # type: ignore[attr-defined]
    row = SectionValue.objects.get(section="helpdeskapp")
    assert row.values == {"reply_within_hours": 4} and row.updated_by == admin
    with pytest.raises(preferences.PreferenceRefused) as refused:
        preferences.save_section("helpdeskapp", {"reply_within_hours": 0})
    assert refused.value.code == "E323" and "reply_within_hours" in refused.value.errors
    with pytest.raises(preferences.PreferenceRefused) as refused:
        preferences.save_section("helpdeskapp", {"colour": "red"})
    assert refused.value.code == "E323"
    preferences.save_section("helpdeskapp", {"reply_within_hours": None})
    assert SectionValue.objects.get(section="helpdeskapp").values == {}
    assert preferences.value("helpdeskapp.reply_within_hours", 0) == 24


def test_details_refuse_a_bad_value_and_an_unknown_field() -> None:
    for values, field in (
        ({"time_zone": "Mars/Olympus"}, "time_zone"),
        ({"currency": "euro"}, "currency"),
        ({"email": "not an email"}, "email"),
        ({"currency_display": "loud"}, "currency_display"),
        ({"colour": "red"}, "colour"),
    ):
        with pytest.raises(preferences.PreferenceRefused) as refused:
            preferences.save_details(values)
        assert refused.value.code == "E323" and field in refused.value.errors, values
    assert not Details.objects.exists()


def test_changes_are_audited_with_who_made_them(admin: Any) -> None:
    preferences.save_details({"name": "Harbour Yoga"}, user=admin)
    preferences.save_details({"name": "Harbour Yoga Studio"}, user=admin)
    preferences.save_section("helpdeskapp", {"greeting": "Hi"}, user=admin)
    preferences.switch("connection", "helpdeskapp.ticket_timeline", False, user=admin)
    logs = ChangeLog.objects.order_by("timestamp")
    details = [log for log in logs if log.content_type.model == "details"]
    assert [log.action for log in details] == ["create", "update"]
    assert details[1].diff["name"] == ["Harbour Yoga", "Harbour Yoga Studio"]
    assert all(log.actor == admin for log in logs if log.content_type.app_label == "preferences")
    assert {log.content_type.model for log in logs} >= {"details", "sectionvalue", "switch"}


# locks


def test_a_locked_value_reads_the_lock_and_cannot_be_changed() -> None:
    locks = {
        "details": {"currency": "EUR"},
        "helpdeskapp": {"reply_within_hours": 48},
        "connections": {"helpdeskapp.ticket_timeline": False},
        "emails": {"helpdeskapp.ticket_closed": False},
    }
    with override_settings(KARNI_PREFERENCES_LOCKED=locks):
        assert preferences.value("details.currency", "") == "EUR"
        assert preferences.value("helpdeskapp.reply_within_hours", 0) == 48
        assert not preferences.active("helpdeskapp.ticket_timeline")
        assert not preferences.email_on("helpdeskapp.ticket_closed")
        for call in (
            lambda: preferences.save_details({"currency": "USD"}),
            lambda: preferences.save_section("helpdeskapp", {"reply_within_hours": 2}),
            lambda: preferences.switch("connection", "helpdeskapp.ticket_timeline", True),
            lambda: preferences.switch("email", "helpdeskapp.ticket_closed", True),
        ):
            with pytest.raises(preferences.PreferenceRefused) as refused:
                call()
            assert refused.value.code == "E324"
        preferences.save_section("helpdeskapp", {"greeting": "Hi"})  # the rest stays open
    assert preferences.value("helpdeskapp.greeting", "") == "Hi"


def test_locks_without_the_app_still_hold() -> None:
    from django.apps import apps

    real = apps.is_installed
    with (
        pytest.MonkeyPatch.context() as patch,
        override_settings(KARNI_PREFERENCES_LOCKED={"helpdeskapp": {"greeting": "Hey"}}),
    ):
        patch.setattr(apps, "is_installed", lambda n: n != "karni.preferences" and real(n))
        assert not preferences.installed()
        assert preferences.value("helpdeskapp.greeting", "") == "Hey"
        assert preferences.value("helpdeskapp.reply_within_hours", 0) == 24
        with pytest.raises(KarniError) as exc:
            preferences.save_section("helpdeskapp", {"greeting": "Hi"})
        assert _code(exc) == "E325"


# connections and emails


def test_a_connection_is_active_when_what_it_needs_is_installed_and_it_is_on() -> None:
    assert preferences.active("helpdeskapp.ticket_timeline")  # timeline installed, on
    assert not preferences.active("loyaltyapp.paid_visits")  # karni_payments absent
    assert not preferences.active("loyaltyapp.visit_events")  # off by default
    assert not preferences.active("nobody.declared_this")
    assert preferences.switch("connection", "loyaltyapp.visit_events", True)
    assert preferences.active("loyaltyapp.visit_events")
    assert not preferences.switch("connection", "helpdeskapp.ticket_timeline", False)
    assert not preferences.active("helpdeskapp.ticket_timeline")
    assert preferences.value("connections.helpdeskapp.ticket_timeline", True) is False
    preferences.switch("connection", "helpdeskapp.ticket_timeline", None)  # the default again
    assert preferences.active("helpdeskapp.ticket_timeline")
    assert not Switch.objects.filter(name="helpdeskapp.ticket_timeline").exists()
    with pytest.raises(KarniError) as exc:
        preferences.switch("connection", "nobody.declared_this", True)
    assert _code(exc) == "E325"


def test_email_kinds_are_declared_or_come_from_a_move() -> None:
    names = {kind.name for kind in preferences.emails()}
    assert {"helpdeskapp.ticket_closed", "rulesapp.purchase_paid"} <= names
    assert preferences.email_on("helpdeskapp.ticket_closed")
    preferences.switch("email", "rulesapp.purchase_paid", False)
    assert not preferences.email_on("rulesapp.purchase_paid")
    assert preferences.value("emails.rulesapp.purchase_paid", True) is False


def test_a_move_email_follows_its_switch_and_the_sender(
    mailoutbox: list[Any], django_capture_on_commit_callbacks: Any
) -> None:
    from decimal import Decimal

    from karni.rules import send_move_email
    from tests.people.conftest import make_user
    from tests.rulesapp.models import Item, Purchase, Shop

    shop = Shop.objects.create(owner=make_user("owner@example.com"), name="Lamps")
    item = Item.objects.create(shop=shop, title="Lamp", price=Decimal("10.00"))
    purchase = Purchase.objects.create(item=item, buyer=make_user("buyer@example.com"))
    preferences.save_details({"name": "Lamp Shop", "sender_email": "shop@lamps.example"})
    assert send_move_email(purchase, "paid") == 1
    assert mailoutbox[0].from_email == "Lamp Shop <shop@lamps.example>"
    preferences.switch("email", "rulesapp.purchase_paid", False)
    assert send_move_email(purchase, "paid") == 0
    assert len(mailoutbox) == 1


def test_override_sets_values_for_a_block() -> None:
    with preferences.override(
        helpdeskapp={"greeting": "Ahoy"},
        connections={"helpdeskapp.ticket_timeline": False},
        details={"name": "Test Studio"},
    ):
        assert preferences.value("helpdeskapp.greeting", "") == "Ahoy"
        assert not preferences.active("helpdeskapp.ticket_timeline")
        assert preferences.details().name == "Test Studio"
    assert preferences.value("helpdeskapp.greeting", "") == "Hello"
    with pytest.raises(KarniError), preferences.override(shop={"x": 1}):
        pass


# declarations


def test_a_section_declaration_is_checked() -> None:
    from pydantic import Field

    for key, model, words in (
        ("Bad Key", None, "lower-case"),
        ("details", None, "reserved"),
        ("helpdeskapp", None, "registered twice"),
    ):

        class Some(preferences.Section):
            size: int = 1

        with pytest.raises(KarniError) as exc:
            preferences.section(key)(model or Some)
        assert _code(exc) == "E321" and words in str(exc.value), key

    class NoDefault(preferences.Section):
        size: int = Field(0, ge=1)

    with pytest.raises(KarniError) as exc:
        preferences.section("someapp")(NoDefault)
    assert _code(exc) == "E321" and "defaults" in str(exc.value)
    assert find_section("someapp") is None


def test_a_connection_declaration_is_checked() -> None:
    for kwargs in (
        {"name": "nodot", "needs": ["events"], "default": True, "describe": "x"},
        {"name": "a.b", "needs": [], "default": True, "describe": "x"},
        {"name": "a.b", "needs": "events", "default": True, "describe": "x"},
        {"name": "a.b", "needs": ["events"], "default": "yes", "describe": "x"},
        {"name": "a.b", "needs": ["events"], "default": True, "describe": ""},
    ):
        with pytest.raises(KarniError) as exc:
            preferences.connection(**kwargs)
        assert _code(exc) == "E322", kwargs


def test_the_checks_report_locks_and_defaults_that_name_nothing() -> None:
    from karni.preferences.checks import check_preferences

    bad = {
        "details": {"colour": "red", "time_zone": "Mars/Olympus"},
        "shop": {"x": 1},
        "helpdeskapp": {"reply_within_hours": 0, "nothing": 1},
        "connections": {"nobody.this": True, "helpdeskapp.ticket_timeline": "yes"},
        "emails": {"helpdeskapp.ticket_closed": "no"},
    }
    with override_settings(KARNI_PREFERENCES_LOCKED=bad):
        found = check_preferences()
    assert {message.id for message in found} == {"karni.E320"}
    text = "\n".join(message.msg for message in found)
    for words in ("colour", "Mars/Olympus", "'shop'", "'nothing'", "nobody.this", "not True"):
        assert words in text, words
    with override_settings(KARNI_PREFERENCES_DEFAULTS={"helpdeskapp": {"reply_within_hours": 0}}):
        assert [m.id for m in check_preferences()] == ["karni.E320"]
    assert check_preferences() == []
