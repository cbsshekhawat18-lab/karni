"""App configuration for the lifecycle test app."""

from __future__ import annotations

from django.apps import AppConfig


class LifecycleAppConfig(AppConfig):
    """Configuration for :mod:`tests.lifecycleapp` (app label ``lifecycleapp``)."""

    name = "tests.lifecycleapp"
    label = "lifecycleapp"
    verbose_name = "Karni lifecycle test app"
