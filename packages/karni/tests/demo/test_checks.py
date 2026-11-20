"""The checks: a malformed account list (E950) and a missing guard (E953)."""

from __future__ import annotations

from typing import Any

from karni.demo.checks import GUARD, check_demo_mode


def ids() -> list[str]:
    return [message.id for message in check_demo_mode()]


def test_a_valid_setup_is_clean(settings: Any) -> None:
    settings.KARNI_DEMO_MODE = True
    settings.KARNI_DEMO_ACCOUNTS = [{"login": "a@example.com"}]
    assert ids() == []


def test_a_malformed_account_list_is_e950(settings: Any) -> None:
    settings.KARNI_DEMO_ACCOUNTS = [{"label": "no login"}]
    found = check_demo_mode()
    assert [m.id for m in found] == ["karni.E950"]
    assert "KARNI_DEMO_ACCOUNTS[0]" in found[0].msg


def test_demo_mode_without_the_guard_is_e953(settings: Any) -> None:
    settings.KARNI_DEMO_MODE = True
    settings.MIDDLEWARE = [m for m in settings.MIDDLEWARE if m != GUARD]
    assert ids() == ["karni.E953"]
    settings.KARNI_DEMO_GUARD_MIDDLEWARE = ["myproject.middleware.Guard"]
    settings.MIDDLEWARE = [*settings.MIDDLEWARE, "myproject.middleware.Guard"]
    assert ids() == []


def test_demo_mode_off_needs_no_guard(settings: Any) -> None:
    settings.KARNI_DEMO_MODE = False
    settings.MIDDLEWARE = [m for m in settings.MIDDLEWARE if m != GUARD]
    assert ids() == []
