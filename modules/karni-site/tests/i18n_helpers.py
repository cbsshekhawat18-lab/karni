"""``two_languages``: a test runs on the site of tests/i18n_urls.py, in English and French."""

from __future__ import annotations

import pytest
from pytest_django import Settings

LOCALE = "django.middleware.locale.LocaleMiddleware"


@pytest.fixture
def two_languages(settings: Settings) -> Settings:
    """English (the default) and French under ``i18n_patterns``, chosen by the address."""
    settings.ROOT_URLCONF = "tests.i18n_urls"
    settings.USE_I18N = True
    settings.LANGUAGE_CODE = "en"
    settings.LANGUAGES = [("en", "English"), ("fr", "French")]
    middleware = [name for name in settings.MIDDLEWARE if name != LOCALE]
    middleware.insert(middleware.index("django.middleware.common.CommonMiddleware"), LOCALE)
    settings.MIDDLEWARE = middleware
    return settings
