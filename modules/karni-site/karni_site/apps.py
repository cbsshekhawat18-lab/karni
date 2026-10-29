"""Django app configuration for ``karni_site``."""

from __future__ import annotations

from django.apps import AppConfig


class KarniSiteConfig(AppConfig):
    """App config for the site module (label ``karni_site``).

    ``ready()`` connects the receivers that clear the cache on every save
    (:mod:`karni_site.signals`).

    Override / escape hatch: subclass this config in your project and point
    ``INSTALLED_APPS`` at the subclass. Keep the label ``karni_site`` so the
    migrations later releases ship keep applying.
    """

    name = "karni_site"
    label = "karni_site"
    verbose_name = "Site"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from karni_site.signals import connect

        connect()
        from karni_site.renditions import connect as connect_renditions

        connect_renditions()
