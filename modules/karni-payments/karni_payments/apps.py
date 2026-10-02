"""Django app configuration for ``karni_payments``."""

from __future__ import annotations

from django.apps import AppConfig


class KarniPaymentsConfig(AppConfig):
    """App config for the Karni payments module (label ``karni_payments``).

    Override / escape hatch: subclass this config in your project and point
    ``INSTALLED_APPS`` at the subclass's dotted path to change startup
    behaviour; the app label must stay ``karni_payments`` so the shipped
    migrations keep applying.
    """

    name = "karni_payments"
    label = "karni_payments"
    verbose_name = "Karni payments"
    default_auto_field = "django.db.models.BigAutoField"
