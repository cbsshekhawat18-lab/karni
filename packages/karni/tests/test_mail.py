"""karni.mail (experimental): an email from a project's own templates."""

from __future__ import annotations

from pathlib import Path

import pytest
from django.core import mail
from django.template import TemplateDoesNotExist
from django.test import override_settings

from karni.mail import render_templated, send_templated


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
