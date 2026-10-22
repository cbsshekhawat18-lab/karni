"""App configuration for the typed field test app."""

from __future__ import annotations

from django.apps import AppConfig


class FieldsAppConfig(AppConfig):
    """Configuration for :mod:`tests.fieldsapp` (app label ``fieldsapp``)."""

    name = "tests.fieldsapp"
    label = "fieldsapp"
    verbose_name = "Karni typed fields test app"
