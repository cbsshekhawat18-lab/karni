"""Django app configuration for Karni.

Adding ``"karni"`` to ``INSTALLED_APPS`` (which :func:`karni.conf.karni_settings`
does by default) wires up startup validation of the merged settings and the
``<app>/events.py`` / ``<app>/listeners.py`` autodiscovery of
:mod:`karni.events`.
"""

from __future__ import annotations

from django.apps import AppConfig


class KarniAppConfig(AppConfig):
    """App config whose ``ready()`` hook validates settings and connects listeners.

    This is Karni's fail-loudly-at-startup hook: as soon as Django finishes
    populating the app registry, the fully merged settings are validated by
    :func:`karni.conf.validation.validate_settings` and any bad value raises
    ``django.core.exceptions.ImproperlyConfigured`` listing every problem.
    Then every installed app's ``events`` and ``listeners`` modules are
    imported (:func:`karni.events.autodiscover`), connecting their receivers
    in web, worker and beat processes alike.

    Last, it connects :mod:`karni.tracing` (the request id on Celery tasks,
    their retries and outgoing email) and the development capture's exception
    hook (:mod:`karni.debug`, inert unless ``DEBUG`` is on).

    Override / escape hatch: set ``KARNI_VALIDATE = False`` in the project's
    settings module to skip validation entirely, ``KARNI_EVENTS_AUTODISCOVER
    = False`` to import listener modules yourself, ``KARNI_REQUEST_ID_EMAILS =
    False`` to leave email alone, or subclass this config and override
    :meth:`ready`.
    """

    name = "karni"
    verbose_name = "Karni"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        """Validate settings (unless ``KARNI_VALIDATE`` is False), then autodiscover listeners."""
        from django.conf import settings

        from karni import checks  # noqa: F401 - registers Karni's system checks

        if getattr(settings, "KARNI_VALIDATE", True):
            from karni.conf.validation import validate_settings

            validate_settings(settings)

        if getattr(settings, "KARNI_EVENTS_AUTODISCOVER", True):
            from karni.events import autodiscover

            autodiscover()

        # One request id across tasks, retries and email (karni.tracing), and
        # the development capture's exception hook (inert with DEBUG off).
        from karni import tracing
        from karni.debug import middleware as debug_middleware

        tracing.connect()
        debug_middleware.connect()
