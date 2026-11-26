"""karni.mail: an email from a project's own templates."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from django.core import mail
from django.template import TemplateDoesNotExist
from django.test import override_settings

from karni.mail import (
    EditedTemplate,
    check_edited,
    find_kind,
    kind_enabled,
    kinds,
    merge_values,
    register_kind,
    render_templated,
    send_templated,
    unregister_kind,
)


@pytest.fixture
def templates(tmp_path: Path):
    folder = tmp_path / "shop" / "email"
    folder.mkdir(parents=True)
    (folder / "confirmed_subject.txt").write_text("Order {{ number }}\nconfirmed\n")
    (folder / "confirmed_body.txt").write_text("Thanks, {{ name }}. {{ frontend_url }}/orders")
    (folder / "plain_subject.txt").write_text("Plain")
    (folder / "plain_body.txt").write_text("Text only")
    (folder / "confirmed_body.html").write_text("<p>Thanks, {{ name }}.</p>")
    setting = [
        {
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "DIRS": [str(tmp_path)],
            "APP_DIRS": True,
        }
    ]
    with override_settings(
        TEMPLATES=setting,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        KARNI_FRONTEND_URL="https://shop.example.com/",
    ):
        yield tmp_path


# The sender and the switches come from karni.preferences (installed here): a query.
@pytest.mark.django_db
def test_the_subject_is_one_line_and_the_bodies_get_the_context(templates: Path) -> None:
    sent = send_templated(
        "shop/email/confirmed", to=["a@example.com"], context={"number": 7, "name": "Ana"}
    )
    assert sent == 1
    [message] = mail.outbox
    assert message.subject == "Order 7 confirmed"
    assert message.to == ["a@example.com"]
    assert message.body == "Thanks, Ana. https://shop.example.com/orders"
    assert message.alternatives[0][0] == "<p>Thanks, Ana.</p>"


def test_the_html_body_is_optional(templates: Path) -> None:
    rendered = render_templated("shop/email/plain")
    assert (rendered.subject, rendered.text, rendered.html) == ("Plain", "Text only", None)


def test_no_address_sends_nothing(templates: Path) -> None:
    assert send_templated("shop/email/plain", to=["", "  "]) == 0
    assert mail.outbox == []


def test_reply_to_and_sender_are_passed_on(templates: Path) -> None:
    send_templated(
        "shop/email/plain",
        to=["a@example.com"],
        from_email="shop@example.com",
        reply_to=["help@example.com"],
        bcc=["log@example.com"],
    )
    [message] = mail.outbox
    assert message.from_email == "shop@example.com"
    assert message.reply_to == ["help@example.com"]
    assert message.bcc == ["log@example.com"]


def test_a_missing_template_is_an_error(templates: Path) -> None:
    with pytest.raises(TemplateDoesNotExist):
        send_templated("shop/email/missing", to=["a@example.com"])


# The sender and the switches come from karni.preferences (installed here): a query.
@pytest.mark.django_db
def test_a_kind_goes_out_in_a_header_and_can_be_switched_off(templates: Path) -> None:
    assert send_templated("shop/email/plain", to=["a@example.com"], kind="shop.plain") == 1
    assert mail.outbox[-1].extra_headers["X-Karni-Kind"] == "shop.plain"
    with override_settings(KARNI_MAIL_DISABLED_KINDS=["shop.plain"]):
        assert send_templated("shop/email/plain", to=["a@example.com"], kind="shop.plain") == 0
        assert send_templated("shop/email/plain", to=["a@example.com"], kind="shop.other") == 1
    assert len(mail.outbox) == 2


@pytest.mark.django_db
def test_silenced_sends_nothing_now_nor_at_the_commit(
    templates: Path, django_capture_on_commit_callbacks
) -> None:
    from django.db import transaction

    from karni.mail import silenced

    with django_capture_on_commit_callbacks(execute=True):
        with silenced():
            assert send_templated("shop/email/plain", to=["a@example.com"]) == 0
            transaction.on_commit(lambda: send_templated("shop/email/plain", to=["b@x.com"]))
    assert mail.outbox == []
    assert send_templated("shop/email/plain", to=["a@example.com"]) == 1


# -- kinds, the source of a business's changes, the restricted engine ----------------------


class _Line:
    def __init__(self, name: str, quantity: int) -> None:
        self.name = name
        self.quantity = quantity
        self.secret = "not declared"


class _Order:
    number = 1042
    total = Decimal("12.50")
    password = "hunter2"  # never declared, so an edited template cannot read it

    def __init__(self) -> None:
        self.lines = [_Line("Mug", 2), _Line("Bowl", 1)]


class EditedSource:
    """A test source: what a business changed, kept in a class attribute."""

    edited: dict[str, EditedTemplate] = {}
    off: set[str] = set()
    sender_address: str | None = None

    def template(self, kind: str) -> EditedTemplate | None:
        return self.edited.get(kind)

    def enabled(self, kind: str) -> bool:
        return kind not in self.off

    def sender(self) -> str | None:
        return self.sender_address


@pytest.fixture
def source(templates: Path):
    register_kind(
        "test.confirmed",
        title="Confirmed",
        template="shop/email/confirmed",
        audience="the buyer",
        fields={"order.number": "The number", "lines.name": "Each line's name", "name": "Name"},
    )
    EditedSource.edited, EditedSource.off, EditedSource.sender_address = {}, set(), None
    with override_settings(KARNI_MAIL_SOURCE="tests.test_mail.EditedSource"):
        yield EditedSource
    unregister_kind("test.confirmed")


def test_a_declared_kind_is_listed_with_its_merge_fields(source: type[EditedSource]) -> None:
    names = [kind.name for kind in kinds()]
    assert "test.confirmed" in names
    assert "accounts.login_code" in names  # core declares the account emails
    found = find_kind("test.confirmed")
    assert found is not None and found.fields["order.number"] == "The number"
    assert find_kind("accounts.login_code").switchable is False  # type: ignore[union-attr]


def test_merge_values_are_plain_and_declared_only() -> None:
    values = merge_values(["order.number", "order.total", "lines.name"], {"order": _Order()})
    assert values["order"] == {"number": 1042, "total": Decimal("12.50")}
    values = merge_values(["order.lines.name"], {"order": _Order()})
    assert values["order"]["lines"] == [{"name": "Mug"}, {"name": "Bowl"}]


def test_an_edited_template_wins_and_sees_the_declared_fields_only(
    source: type[EditedSource],
) -> None:
    source.edited["test.confirmed"] = EditedTemplate(
        subject="Order {{ order.number }}\nis yours",
        text="{% for line in lines %}{{ line.name }};{% endfor %}"
        " [{{ order.password }}] {{ name }} https://shop.example.com/o",
    )
    context = {"order": _Order(), "lines": _Order().lines, "name": "Mira"}
    sent = send_templated(
        "shop/email/confirmed", to=["a@example.com"], context=context, kind="test.confirmed"
    )
    assert sent == 1
    [message] = mail.outbox
    assert message.subject == "Order 1042 is yours"
    assert message.body == "Mug;Bowl; [] Mira https://shop.example.com/o"
    html, kind = message.alternatives[0]
    assert kind == "text/html" and '<a href="https://shop.example.com/o"' in html
    # Without an edit, the files as before.
    source.edited.clear()
    rendered = render_templated("shop/email/confirmed", context, kind="test.confirmed")
    assert rendered.text.startswith("Thanks, Mira.")


def test_the_restricted_engine_loads_no_code_and_no_other_template() -> None:
    assert "text" in check_edited("Hi", "{% load static %}{% static 'a.css' %}")
    assert "text" in check_edited("Hi", '{% include "shop/email/plain_body.txt" %}')
    assert "subject" in check_edited("{% extends 'base.html' %}", "Body")
    assert "subject" in check_edited("  ", "Body")
    assert check_edited("Order {{ order.number }}", "{% if name %}Hi {{ name }}{% endif %}") == {}


def test_the_source_switches_an_email_off_and_names_the_sender(
    source: type[EditedSource],
) -> None:
    source.off.add("test.confirmed")
    source.sender_address = "Corner Shop <hello@corner.example>"
    context = {"name": "Mira", "number": 7}
    assert send_templated("shop/email/plain", to=["a@example.com"], kind="test.confirmed") == 0
    assert send_templated("shop/email/plain", to=["a@example.com"], context=context) == 1
    assert mail.outbox[0].from_email == "Corner Shop <hello@corner.example>"
    # A sign-in code is never switched off.
    source.off.add("accounts.login_code")
    assert kind_enabled("accounts.login_code")


def test_an_account_email_follows_an_edit_and_the_sender(
    source: type[EditedSource], django_user_model: Any
) -> None:
    from karni.accounts.emails import AccountsEmail, DjangoEmailBackend

    source.edited["accounts.login_code"] = EditedTemplate(
        subject="Your code for Corner Shop", text="Code: {{ code }} ({{ ttl_minutes }} min)"
    )
    source.sender_address = "Corner Shop <hello@corner.example>"
    DjangoEmailBackend().send(
        AccountsEmail("login_code", "a@example.com", {"code": "123456", "ttl_minutes": 10})
    )
    [message] = mail.outbox
    assert (message.subject, message.body) == ("Your code for Corner Shop", "Code: 123456 (10 min)")
    assert message.from_email == "Corner Shop <hello@corner.example>"
    assert message.extra_headers["X-Karni-Kind"] == "accounts.login_code"


# The sender and the business's details come from karni.preferences (installed here).
@pytest.mark.django_db
def test_a_preview_renders_with_the_latest_record_else_the_declared_samples() -> None:
    from karni import preferences
    from karni.mail import (
        EditedTemplate,
        merge_values,
        register_kind,
        render_edited,
        sample_context,
        unregister_kind,
    )

    latest: list[dict[str, object]] = []
    kind = register_kind(
        "tests.visit_booked",
        title="Visit booked",
        template="tests/email/visit_booked",
        fields={
            "business.name": "The business's name",
            "visit.day": "The day",
            "visit.room": "The room",
            "guests.name": "Each guest's name",
        },
        sample=lambda: latest[-1] if latest else None,
        samples={"visit": {"day": "Monday"}, "guests": [{"name": "Sam"}]},
    )
    edited = EditedTemplate(
        "{{ business.name }} {{ visit.day }}",
        "{{ visit.room }} {% for guest in guests %}{{ guest.name }} {% endfor %}",
    )
    try:
        preferences.save_details({"name": "Harbour Yoga"})
        before = render_edited(edited, merge_values(kind.fields, sample_context(kind)))
        # no record yet: the declared samples, and a field nobody declared shows its path
        assert before.subject == "Harbour Yoga Monday"
        assert before.text == "[visit.room] Sam "
        latest.append({"visit": {"day": "Friday", "room": "Blue"}, "guests": [{"name": "Ada"}]})
        after = render_edited(edited, merge_values(kind.fields, sample_context(kind.name)))
        assert (after.subject, after.text) == ("Harbour Yoga Friday", "Blue Ada ")
    finally:
        unregister_kind("tests.visit_booked")
