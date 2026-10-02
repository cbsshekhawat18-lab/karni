"""App configuration for the performance test app."""

from __future__ import annotations

from django.apps import AppConfig


class PerfAppConfig(AppConfig):
    """Configuration for :mod:`tests.perfapp` (app label ``perfapp``)."""

    name = "tests.perfapp"
    label = "perfapp"
    verbose_name = "Karni performance test app"
