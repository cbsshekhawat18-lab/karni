"""App configuration for the taxonomy test app."""

from __future__ import annotations

from django.apps import AppConfig


class TaxoAppConfig(AppConfig):
    """Configuration for :mod:`tests.taxoapp` (app label ``taxoapp``)."""

    name = "tests.taxoapp"
    label = "taxoapp"
    verbose_name = "Karni taxonomy test app"
