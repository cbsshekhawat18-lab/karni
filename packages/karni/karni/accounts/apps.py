"""Django app configuration for ``karni.accounts``."""

from __future__ import annotations

from importlib import import_module

from django.apps import AppConfig


class KarniAccountsConfig(AppConfig):
    """App config for Karni's accounts app (label ``karni_accounts``).

    ``ready()`` loads the optional ``karni.accounts.signals`` module when it
    exists, so signal receivers (e.g. the allauth email-verification mirror
    used by social auth) register themselves at startup without projects
    importing anything.

    Override / escape hatch: subclass this config in your project and point
    ``INSTALLED_APPS`` at the subclass's dotted path to change startup
    behaviour; the app label must stay ``karni_accounts`` so the shipped
    migrations keep applying.
    """

    name = "karni.accounts"
    label = "karni_accounts"
    verbose_name = "Karni accounts"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        """Register the app's signal receivers, when a signals module is present."""
        from django.utils.module_loading import module_has_submodule

        import karni.accounts

        if module_has_submodule(karni.accounts, "signals"):
            import_module("karni.accounts.signals")
