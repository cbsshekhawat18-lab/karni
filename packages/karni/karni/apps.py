"""Django app configuration for Karni.

Adding ``"karni"`` to ``INSTALLED_APPS`` (which :func:`karni.conf.karni_settings`
does by default) wires up startup validation of the merged settings.
"""

from __future__ import annotations

from django.apps import AppConfig


class KarniAppConfig(AppConfig):
    """App config whose ``ready()`` hook validates the project settings.

    This is Karni's fail-loudly-at-startup hook: as soon as Django finishes
    populating the app registry, the fully merged settings are validated by
    :func:`karni.conf.validation.validate_settings` and any bad value raises
    ``django.core.exceptions.ImproperlyConfigured`` listing every problem.

    Override / escape hatch: set ``KARNI_VALIDATE = False`` in the project's
    settings module to skip validation entirely, or replace validation by
    subclassing this config and overriding :meth:`ready`.
    """

    name = "karni"
    verbose_name = "Karni"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        """Validate the merged Django settings unless ``KARNI_VALIDATE`` is False."""
        from django.conf import settings

        from karni import checks  # noqa: F401 - registers Karni's system checks

        if getattr(settings, "KARNI_VALIDATE", True):
            from karni.conf.validation import validate_settings

            validate_settings(settings)
