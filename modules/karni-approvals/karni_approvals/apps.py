"""Django app configuration for ``karni_approvals``."""

from __future__ import annotations

from django.apps import AppConfig


class KarniApprovalsConfig(AppConfig):
    """App config for the approvals module (label ``karni_approvals``).

    ``ready()`` connects the write interceptor to ``karni.signals.pre_write``
    so a guarded change becomes a pending change instead of a write.

    Override / escape hatch: subclass this config in your project and point
    ``INSTALLED_APPS`` at the subclass; keep the label ``karni_approvals`` so
    the shipped migrations keep applying.
    """

    name = "karni_approvals"
    label = "karni_approvals"
    verbose_name = "Karni approvals"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from karni_approvals.interception import connect

        connect()
