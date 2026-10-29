"""App configuration for the external tables test app."""

from __future__ import annotations

from django.apps import AppConfig


class ExternalAppConfig(AppConfig):
    """Configuration for :mod:`tests.externalapp` (app label ``externalapp``)."""

    name = "tests.externalapp"
    label = "externalapp"
    verbose_name = "Karni external tables test app"
