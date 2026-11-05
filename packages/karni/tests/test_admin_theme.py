"""The admin is light only: no theme switch anywhere, whatever the browser prefers.

``KARNI_ADMIN_THEME`` was removed before it was released: ``UNFOLD["THEME"]``
is ``"light"``, which pins unfold's light palette and hides its switch.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from karni.conf import karni_settings


def _settings(**overrides: Any) -> dict[str, Any]:
    namespace: dict[str, Any] = {"SECRET_KEY": "x" * 50}
    karni_settings(namespace, env_name="dev", **overrides)
    return namespace


def test_light_is_the_only_theme_and_the_setting_is_gone() -> None:
    namespace = _settings()
    assert namespace["UNFOLD"]["THEME"] == "light"
    assert "KARNI_ADMIN_THEME" not in namespace


def test_a_project_unfold_dict_is_light_too() -> None:
    namespace = _settings(UNFOLD={"SITE_TITLE": "Ops"})
    assert namespace["UNFOLD"]["THEME"] == "light"


def test_an_explicit_unfold_theme_wins() -> None:
    namespace = _settings(UNFOLD={"SITE_TITLE": "Ops", "THEME": "dark"})
    assert namespace["UNFOLD"]["THEME"] == "dark"


@pytest.fixture
def staff_client(db: None) -> Client:
    user = get_user_model().objects.create_superuser(
        email="admin@example.com", password="s3cret-pass-123"
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.parametrize("path", ["/admin/", "/admin/adminapp/category/", "/admin/login/"])
def test_no_page_has_a_theme_switch_and_all_are_light(staff_client: Client, path: str) -> None:
    html = (Client() if path.endswith("login/") else staff_client).get(path).content.decode()
    assert "theme('light')" in html
    assert "switchTheme" not in html


def test_a_browser_in_dark_mode_still_gets_the_light_admin(staff_client: Client) -> None:
    """The page is light whatever the browser sends, and no stylesheet follows the system scheme."""
    html = staff_client.get(
        "/admin/", headers={"Sec-CH-Prefers-Color-Scheme": "dark"}
    ).content.decode()
    assert 'class="light"' in html and 'class="dark"' not in html
    from pathlib import Path

    import karni.admin

    static = Path(karni.admin.__file__).parent / "static" / "karni"
    for sheet in static.glob("*.css"):
        assert "prefers-color-scheme" not in sheet.read_text(encoding="utf-8"), sheet.name
