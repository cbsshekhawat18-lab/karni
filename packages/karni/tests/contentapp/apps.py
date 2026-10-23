"""App configuration for the content loading test app."""

from __future__ import annotations

from django.apps import AppConfig


class ContentAppConfig(AppConfig):
    """Configuration for :mod:`tests.contentapp` (app label ``contentapp``)."""

    name = "tests.contentapp"
    label = "contentapp"
    verbose_name = "Karni content loading test app"
