"""App configuration for the rules test app."""

from __future__ import annotations

from django.apps import AppConfig


class RulesAppConfig(AppConfig):
    """Configuration for :mod:`tests.rulesapp` (app label ``rulesapp``)."""

    name = "tests.rulesapp"
    label = "rulesapp"
    verbose_name = "Karni rules test app"
