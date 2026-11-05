"""App config for ``karni.navigation``: the ``NavItem`` table of the database menu."""

from __future__ import annotations

from django.apps import AppConfig


class KarniNavigationConfig(AppConfig):
    """Experimental. ``karni.navigation`` (label ``karni_navigation``).

    Add it to ``INSTALLED_APPS`` only with ``KARNI_NAVIGATION = "db"``: it
    brings the ``NavItem`` table and its admin. The settings source, the
    endpoint and the check work without it.
    """

    name = "karni.navigation"
    label = "karni_navigation"
    verbose_name = "Karni navigation"
    default_auto_field = "django.db.models.BigAutoField"
