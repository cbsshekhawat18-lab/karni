"""Django app configuration for ``karni_commerce``."""

from __future__ import annotations

from django.apps import AppConfig


class KarniCommerceConfig(AppConfig):
    """App config for the Karni commerce module (label ``karni_commerce``).

    ``ready()`` imports ``<app>/sellables.py`` of every installed app, where
    each app registers the kinds it sells (:mod:`karni_commerce.sellables`).

    Override / escape hatch: subclass this config and point ``INSTALLED_APPS``
    at it to change startup. The app label must stay ``karni_commerce`` so the
    shipped migrations keep applying.
    """

    name = "karni_commerce"
    label = "karni_commerce"
    verbose_name = "Karni commerce"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from karni_commerce import sellables

        sellables.autodiscover()
