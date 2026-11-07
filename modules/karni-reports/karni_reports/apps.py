"""Django app configuration for ``karni_reports``."""

from __future__ import annotations

from django.apps import AppConfig


class KarniReportsConfig(AppConfig):
    """App config for the reports module (label ``karni_reports``).

    ``ready()`` imports the ``reports`` module of every installed app, where
    projects declare their reports (:func:`karni_reports.register`).

    Override / escape hatch: subclass this config and point ``INSTALLED_APPS``
    at the subclass (``ready()`` without discovery, then register reports
    yourself); keep the label so the shipped migrations keep applying.
    """

    name = "karni_reports"
    label = "karni_reports"
    verbose_name = "Karni reports"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from karni_reports.registry import autodiscover

        autodiscover()
