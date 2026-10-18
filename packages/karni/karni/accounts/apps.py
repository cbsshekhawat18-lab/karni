"""Django app configuration for ``karni.accounts``."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from django.apps import AppConfig


class KarniAccountsConfig(AppConfig):
    """App config for Karni's accounts app (label ``karni_accounts``).

    ``ready()`` loads the optional ``karni.accounts.signals`` module when it
    exists, so signal receivers (e.g. the allauth email-verification mirror
    used by social auth) register themselves at startup without projects
    importing anything, and connects the ``post_migrate`` role sync
    (``KARNI_ROLES`` → the role tables; off with ``KARNI_ROLES_AUTOSYNC = False``).

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
        from django.db.models.signals import post_migrate
        from django.utils.module_loading import module_has_submodule

        import karni.accounts

        if module_has_submodule(karni.accounts, "signals"):
            import_module("karni.accounts.signals")
        post_migrate.connect(sync_roles_after_migrate, sender=self, dispatch_uid="karni.sync_roles")


def sync_roles_after_migrate(sender: AppConfig, **kwargs: Any) -> None:
    """``post_migrate`` receiver: reconcile the role tables with ``KARNI_ROLES``.

    Runs once per ``migrate`` (the sender is this app), on the database just
    migrated, and only when ``KARNI_ROLES_AUTOSYNC`` is on. The report goes
    to the migrate output's verbosity level: nothing at 0, a summary line at 1,
    the full report above.
    """
    from django.conf import settings

    from karni.accounts.roles import sync_roles

    if not getattr(settings, "KARNI_ROLES_AUTOSYNC", True):
        return
    report = sync_roles()
    verbosity = kwargs.get("verbosity", 1)
    stdout = kwargs.get("stdout")
    if verbosity >= 1 and stdout is not None and (report.created_roles or report.updated_roles):
        stdout.write(report.render() + "\n")
