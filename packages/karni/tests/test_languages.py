"""``karni.E971`` / ``karni.W971``: a LANGUAGES code Django has no LANG_INFO entry for."""

from __future__ import annotations

import pytest
from django.conf.locale import LANG_INFO
from django.template.loader import render_to_string
from django.test import override_settings

from karni import languages

HELPER = "unfold/helpers/language_switch.html"
ENGLISH = ("en", "English")


def test_the_admin_menu_fails_for_such_a_language_whatever_its_switch_says() -> None:
    """Why the check is an error: the page breaks even with the language switch off."""
    with override_settings(LANGUAGES=[ENGLISH, ("xx", "Nowhere")]):
        for show in (True, False):
            with pytest.raises(KeyError, match="Unknown language code xx"):
                render_to_string(HELPER, {"show_languages": show})


def test_a_language_django_cannot_describe_is_an_error_with_the_entry_to_add() -> None:
    with override_settings(LANGUAGES=[ENGLISH, ("xx", "Nowhere"), ("yy", "Elsewhere")]):
        found = languages.check_languages()
    assert [message.id for message in found] == ["karni.E971", "karni.E971"]
    assert all(message.level >= 40 for message in found)
    first = found[0]
    assert "'xx' (Nowhere)" in first.msg and "Unknown language code xx" in first.msg
    assert "admin" in first.msg
    hint = first.hint or ""
    assert "LANG_INFO.update" in hint and '"bidi": False' in hint
    assert (
        '"code": "xx"' in hint and '"name": "Nowhere"' in hint and '"name_local": "Nowhere"' in hint
    )
    assert "'yy' (Elsewhere)" in found[1].msg


def test_the_entry_the_message_shows_registers_the_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with override_settings(LANGUAGES=[ENGLISH, ("xx", "Nowhere")]):
        assert languages.undescribed_languages() == ["xx"]
        monkeypatch.setitem(
            LANG_INFO,
            "xx",
            {"bidi": False, "code": "xx", "name": "Nowhere", "name_local": "Nowhere"},
        )
        assert languages.check_languages() == []
        render_to_string(HELPER, {"show_languages": False})  # the page no longer breaks


def test_a_regional_code_is_described_by_its_language() -> None:
    with override_settings(LANGUAGES=[ENGLISH, ("de-at", "Austrian German"), ("pt-br", "Brazil")]):
        assert languages.check_languages() == []


def test_without_the_admin_it_is_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(languages.apps, "is_installed", lambda name: False)
    with override_settings(LANGUAGES=[ENGLISH, ("xx", "Nowhere")]):
        (message,) = languages.check_languages()
    assert message.id == "karni.W971" and message.level < 40
    assert "a template" in message.msg


def test_the_default_languages_are_all_described() -> None:
    assert languages.check_languages() == []


def test_the_check_is_registered() -> None:
    from django.core.checks.registry import registry

    assert languages.check_languages in registry.registered_checks
