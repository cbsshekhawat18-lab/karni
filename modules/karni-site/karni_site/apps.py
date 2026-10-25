"""Django app configuration for ``karni_site``."""

from __future__ import annotations

from django.apps import AppConfig


class KarniSiteConfig(AppConfig):
    """App config for the site module (label ``karni_site``).

    Override / escape hatch: subclass this config in your project and point
    ``INSTALLED_APPS`` at the subclass. Keep the label ``karni_site`` so the
    migrations later releases ship keep applying.
    """

    name = "karni_site"
    label = "karni_site"
    verbose_name = "Karni site"
    default_auto_field = "django.db.models.BigAutoField"
