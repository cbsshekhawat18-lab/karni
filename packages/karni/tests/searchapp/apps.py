"""App configuration for the cross-model search test app."""

from __future__ import annotations

from django.apps import AppConfig


class SearchAppConfig(AppConfig):
    """Configuration for :mod:`tests.searchapp` (app label ``searchapp``)."""

    name = "tests.searchapp"
    label = "searchapp"
    verbose_name = "Karni search test app"
