"""App configuration for the help desk test app."""

from __future__ import annotations

from django.apps import AppConfig


class DeskAppConfig(AppConfig):
    """Configuration for :mod:`tests.deskapp` (app label ``deskapp``)."""

    name = "tests.deskapp"
    label = "deskapp"
    verbose_name = "Karni family events test desk"
    default_auto_field = "django.db.models.BigAutoField"
