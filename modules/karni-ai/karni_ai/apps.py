"""Django app configuration for ``karni_ai``."""

from __future__ import annotations

from django.apps import AppConfig


class KarniAiConfig(AppConfig):
    """App config for the AI extraction module (label ``karni_ai``).

    Override / escape hatch: subclass this config in your project and point
    ``INSTALLED_APPS`` at the subclass. Keep the label ``karni_ai`` so the
    shipped migrations keep applying.
    """

    name = "karni_ai"
    label = "karni_ai"
    verbose_name = "Karni AI"
    default_auto_field = "django.db.models.BigAutoField"
