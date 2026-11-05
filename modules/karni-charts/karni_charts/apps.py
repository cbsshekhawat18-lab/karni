"""Django app configuration for ``karni_charts``."""

from __future__ import annotations

from django.apps import AppConfig


class KarniChartsConfig(AppConfig):
    """App config for the charts module (label ``karni_charts``).

    Override / escape hatch: subclass this config in your project and point
    ``INSTALLED_APPS`` at the subclass. Keep the label ``karni_charts`` so the
    shipped migrations keep applying.
    """

    name = "karni_charts"
    label = "karni_charts"
    verbose_name = "Karni charts"
    default_auto_field = "django.db.models.BigAutoField"
