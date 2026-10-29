"""``KARNI_ADMIN_THEME``: the admin is light only by default, dark or the switch on request.

The admin reads the setting on every request, so a value assigned after
``karni_settings()`` (``override_settings`` here) takes effect.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.test import Client, override_settings

from karni.conf import karni_settings
from karni.conf.admin_theme import theme, theme_value
from karni.conf.validation import validate_settings


def _settings(**overrides: Any) -> dict[str, Any]:
    namespace: dict[str, Any] = {"SECRET_KEY": "x" * 50}
    karni_settings(namespace, env_name="dev", **overrides)
    return namespace


def test_light_is_the_default_and_unfold_reads_it_per_request() -> None:
    namespace = _settings()
    assert namespace["KARNI_ADMIN_THEME"] == "light"
    assert namespace["UNFOLD"]["THEME"] is theme
    assert theme(None) == "light"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("light", "light"), ("dark", "dark"), ("auto", None), ("", "light"), (None, "light")],
)
def test_each_value_maps_to_unfolds_theme(value: Any, expected: str | None) -> None:
    assert theme_value(value) == expected


def test_an_unknown_value_is_refused_at_startup() -> None:
    with pytest.raises(ImproperlyConfigured, match="KARNI_ADMIN_THEME"):
        validate_settings({"KARNI_ADMIN_THEME": "sepia"})


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


def _admin_page(client: Client) -> str:
    response = client.get("/admin/")
    assert response.status_code == 200
    return response.content.decode()


def test_the_admin_is_light_with_no_theme_switch(staff_client: Client) -> None:
    html = _admin_page(staff_client)
    assert 'class="light"' in html and "theme('light')" in html
    assert "switchTheme('dark')" not in html


def test_the_login_screen_is_light_with_no_theme_switch(db: None) -> None:
    html = Client().get("/admin/login/").content.decode()
    assert "theme('light')" in html and "switchTheme('dark')" not in html


def test_auto_brings_the_switch_back(staff_client: Client) -> None:
    with override_settings(KARNI_ADMIN_THEME="auto"):
        html = _admin_page(staff_client)
    assert "switchTheme('dark')" in html and 'class="light"' not in html


def test_dark_pins_the_dark_palette(staff_client: Client) -> None:
    with override_settings(KARNI_ADMIN_THEME="dark"):
        html = _admin_page(staff_client)
    assert 'class="dark"' in html and "switchTheme('light')" not in html
