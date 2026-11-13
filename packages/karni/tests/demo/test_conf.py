"""The settings, the demo accounts and the codes of a bad setting."""

from __future__ import annotations

from typing import Any

import pytest

from karni.demo import conf
from karni.exceptions import KarniValueError

from .conftest import CUSTOMER, STAFF


def test_demo_mode_is_off_by_default(settings: Any) -> None:
    assert conf.demo_mode() is False


def test_the_unset_account_list_is_the_account_karni_seed_makes(settings: Any) -> None:
    settings.KARNI_DEMO_ACCOUNTS = []
    [only] = conf.accounts()
    assert only.login == STAFF and only.roles is None and only.staff and only.superuser
    assert only.secret == "karni-password"


def test_accounts_keep_their_order_and_fill_the_defaults(demo: Any) -> None:
    staff, customer = conf.accounts()
    assert (staff.login, staff.label, staff.roles) == (STAFF, "Staff", None)
    assert (customer.login, customer.roles, customer.can) == (
        CUSTOMER,
        ("customer",),
        "Place orders.",
    )
    assert customer.staff is False and customer.secret == "karni-password"


def test_an_account_may_have_its_own_password(settings: Any) -> None:
    settings.KARNI_DEMO_ACCOUNTS = [{"login": "a@example.com", "password": "own-password-1"}]
    [account] = conf.accounts()
    assert account.secret == "own-password-1" and account.label == "a@example.com"


@pytest.mark.parametrize(
    "setting, message",
    [
        ("text", "not a list of dicts"),
        (["a@example.com"], r"KARNI_DEMO_ACCOUNTS\[0\] is 'a@example.com', not a dict"),
        ([{"label": "x"}], "needs a non-empty string 'login'"),
        ([{"login": "a@example.com", "role": ["x"]}], r"unknown keys \['role'\]"),
        ([{"login": "a@example.com", "roles": "most"}], "use a list of role names, or 'all'"),
        ([{"login": "a@example.com", "roles": [1]}], "use a list of role names"),
        ([{"login": "a@example.com", "password": ""}], "non-empty string"),
        ([{"login": "a@example.com"}, {"login": "A@example.com"}], "lists A@example.com twice"),
    ],
)
def test_a_malformed_list_raises_e950(settings: Any, setting: Any, message: str) -> None:
    settings.KARNI_DEMO_ACCOUNTS = setting
    with pytest.raises(KarniValueError, match=message) as caught:
        conf.accounts()
    assert caught.value.code == "E950"


def test_find_account_ignores_case(demo: Any) -> None:
    found = conf.find_account("CUSTOMER@example.com")
    assert found is not None and found.label == "Customer"
    assert conf.find_account("nobody@example.com") is None


def test_the_short_environment_names_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """The defaults are read when karni.conf.base is imported, so a fresh process reads them."""
    import subprocess
    import sys

    code = (
        "from karni.conf.base import BASE as b; "
        "print(b['KARNI_DEMO_MODE'], b['KARNI_DEMO_RESET_HOURS'], b['KARNI_DEMO_SEED'])"
    )

    def run(**env: str) -> str:
        for name in ("DEMO_MODE", "DEMO_RESET_HOURS", "DEMO_SEED", "KARNI_DEMO_RESET_HOURS"):
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        done = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=120
        )
        return done.stdout.strip()

    assert run() == "False 24 42"
    assert run(DEMO_MODE="True", DEMO_RESET_HOURS="6", DEMO_SEED="7") == "True 6 7"
    assert run(DEMO_RESET_HOURS="6", KARNI_DEMO_RESET_HOURS="12") == "False 12 42"  # KARNI_ wins


def test_the_stamp_sits_next_to_a_sqlite_file_else_in_the_project(
    settings: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.KARNI_DEMO_RESET_STAMP = ""
    database = settings.DATABASES["default"]
    monkeypatch.setitem(database, "NAME", str(tmp_path / "db" / "x.sqlite3"))
    assert conf.stamp_path() == tmp_path / "db" / "demo-reset.json"
    monkeypatch.setitem(database, "NAME", "shop")
    settings.BASE_DIR = tmp_path
    assert conf.stamp_path() == tmp_path / "data" / "demo-reset.json"


def test_the_app_index_defaults_to_the_frontend_build(settings: Any, tmp_path: Any) -> None:
    settings.KARNI_DEMO_APP_INDEX = ""
    settings.BASE_DIR = tmp_path
    assert conf.app_index() == tmp_path / "frontend" / "dist" / "index.html"


def test_patterns_match_a_path_or_a_prefix() -> None:
    assert conf.matches("/api/contact/", ["/api/contact/"])
    assert conf.matches("/api/contact/send/", ["/api/contact/*"])
    assert not conf.matches("/api/contacts/", ["/api/contact/"])
    assert not conf.matches("/api/x/", None)
