"""App configuration for the wide-model test app."""

from __future__ import annotations

from django.apps import AppConfig


class WideAppConfig(AppConfig):
    """Configuration for :mod:`tests.wideapp` (app label ``wideapp``)."""

    name = "tests.wideapp"
    label = "wideapp"
    verbose_name = "Karni wide-model test app"
