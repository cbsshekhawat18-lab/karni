"""``KARNI_NAVIGATION`` at startup (experimental): one error lists every problem and its code."""

from __future__ import annotations

from typing import Any

import pytest

from karni.conf.validation import validate_settings
from karni.exceptions import KarniImproperlyConfigured


def _settings(**extra: Any) -> dict[str, Any]:
    from django.conf import settings

    names = ("SECRET_KEY", "DEBUG", "ALLOWED_HOSTS", "DATABASES", "CACHES", "INSTALLED_APPS")
    return {**{name: getattr(settings, name) for name in names}, **extra}


def test_a_valid_menu_and_db_with_the_app_pass() -> None:
    validate_settings(_settings(KARNI_NAVIGATION=[{"label": "Home", "route": "/"}]))
    validate_settings(_settings(KARNI_NAVIGATION="db"))  # karni.navigation is installed here
    validate_settings(_settings(KARNI_NAVIGATION=None))


def test_every_problem_is_listed_with_its_code() -> None:
    menu = [
        {"label": "Products", "route": "products"},
        {"label": "Home", "route": "/", "requires": "x"},
    ]
    with pytest.raises(KarniImproperlyConfigured) as caught:
        validate_settings(_settings(KARNI_NAVIGATION=menu, KARNI_NAVIGATION_PAGES="routes.tsx"))
    message = str(caught.value)
    assert "KARNI_NAVIGATION[0]: route 'products' must be an app path" in message
    assert "(E530)" in message and "(E532)" in message
    assert "KARNI_NAVIGATION_PAGES = 'routes.tsx' must be a list" in message


def test_db_without_the_app_is_e531() -> None:
    apps = [app for app in _settings()["INSTALLED_APPS"] if app != "karni.navigation"]
    with pytest.raises(KarniImproperlyConfigured) as caught:
        validate_settings(_settings(KARNI_NAVIGATION="db", INSTALLED_APPS=apps))
    assert "comes with the 'karni.navigation' app" in str(caught.value)
    assert "(E531)" in str(caught.value)
