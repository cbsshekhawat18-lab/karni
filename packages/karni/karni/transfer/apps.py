"""Django app configuration for ``karni.transfer`` (import and export)."""

from __future__ import annotations

from django.apps import AppConfig


class KarniTransferConfig(AppConfig):
    """App config for the import/export tables (label ``karni_transfer``)."""

    name = "karni.transfer"
    label = "karni_transfer"
    verbose_name = "Karni import and export"
    default_auto_field = "django.db.models.BigAutoField"
