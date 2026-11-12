"""App configuration for the help desk test part."""

from __future__ import annotations

from django.apps import AppConfig


class HelpdeskAppConfig(AppConfig):
    """Configuration for :mod:`tests.helpdeskapp` (app label ``helpdeskapp``)."""

    name = "tests.helpdeskapp"
    label = "helpdeskapp"
    verbose_name = "Karni help desk test part"
