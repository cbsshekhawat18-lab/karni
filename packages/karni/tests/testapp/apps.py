"""App configuration for the api test app."""

from __future__ import annotations

from django.apps import AppConfig


class TestAppConfig(AppConfig):
    """Configuration for :mod:`tests.testapp` (app label ``testapp``)."""

    name = "tests.testapp"
    label = "testapp"
    verbose_name = "Karni API test app"
