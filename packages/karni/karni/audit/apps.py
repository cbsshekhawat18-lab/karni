"""App config: connects the capture receivers once the model registry is ready."""

from __future__ import annotations

from django.apps import AppConfig


class KarniAuditConfig(AppConfig):
    name = "karni.audit"
    label = "karni_audit"
    verbose_name = "Karni audit"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from karni.audit.capture import connect

        connect()
