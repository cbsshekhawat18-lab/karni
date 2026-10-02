"""App configuration for the scope-pipeline test app."""

from __future__ import annotations

from django.apps import AppConfig


class ScopeAppConfig(AppConfig):
    """Configuration for :mod:`tests.scopeapp` (app label ``scopeapp``)."""

    name = "tests.scopeapp"
    label = "scopeapp"
    verbose_name = "Karni scope test app"
