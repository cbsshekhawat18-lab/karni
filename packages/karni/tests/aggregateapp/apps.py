"""App configuration for the aggregations test app."""

from __future__ import annotations

from django.apps import AppConfig


class AggregateAppConfig(AppConfig):
    """Configuration for :mod:`tests.aggregateapp` (app label ``aggregateapp``)."""

    name = "tests.aggregateapp"
    label = "aggregateapp"
    verbose_name = "Karni aggregations test app"
