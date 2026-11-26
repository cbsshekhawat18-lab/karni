"""App config for ``karni.preferences``: the preferences contract (label ``preferences``)."""

from __future__ import annotations

from django.apps import AppConfig


class PreferencesConfig(AppConfig):
    """``karni.preferences`` (label ``preferences``): Details, SectionValue, Switch.

    Add ``"karni.preferences"`` to ``INSTALLED_APPS`` (``karni build`` does it
    for ``features: {preferences: true}``) and run migrate.

    ``ready()`` imports every installed app's ``preferences.py`` and
    ``connections.py`` (unless ``KARNI_PREFERENCES_AUTODISCOVER`` is False),
    registers the system checks, and keeps one read of each table per request
    (dropped on every change).

    Override / escape hatch: subclass this config and point ``INSTALLED_APPS``
    at it (the label must stay ``preferences`` so the migrations apply).
    """

    name = "karni.preferences"
    label = "preferences"
    verbose_name = "Preferences"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from django.conf import settings
        from django.core.signals import request_finished, request_started
        from django.db.models.signals import post_delete, post_save

        from karni.preferences import checks, registry, services  # noqa: F401 - the checks
        from karni.preferences.models import Details, SectionValue, Switch

        request_started.connect(services.start_request, dispatch_uid="karni.preferences.start")
        request_finished.connect(services.end_request, dispatch_uid="karni.preferences.end")
        for model in (Details, SectionValue, Switch):
            uid = f"karni.preferences.forget.{model.__name__}"
            post_save.connect(services.forget, sender=model, dispatch_uid=uid)
            post_delete.connect(services.forget, sender=model, dispatch_uid=f"{uid}.delete")
        if getattr(settings, "KARNI_PREFERENCES_AUTODISCOVER", True):
            registry.autodiscover()
