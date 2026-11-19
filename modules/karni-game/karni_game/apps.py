"""Django app configuration for ``karni_game``."""

from __future__ import annotations

from django.apps import AppConfig


class KarniGameConfig(AppConfig):
    """App config for the Karni game module (label ``karni_game``).

    ``ready()`` registers the check that the people contract is installed
    (``karni.GAME001``) and imports ``<app>/game.py`` of every installed app,
    where a project registers its save migrations and run checks
    (:mod:`karni_game.hooks`).

    Override / escape hatch: subclass this config and point ``INSTALLED_APPS``
    at it to change startup. The app label must stay ``karni_game`` so the
    shipped migrations keep applying. ``KARNI_GAME_AUTODISCOVER = False``
    stops the import of ``<app>/game.py``.
    """

    name = "karni_game"
    label = "karni_game"
    verbose_name = "Karni games"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from django.core import checks

        from karni_game import hooks
        from karni_game.checks import people_installed

        checks.register(people_installed)
        hooks.autodiscover()
