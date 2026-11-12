"""App config for ``karni.timeline``: the timeline contract (label ``timeline``)."""

from __future__ import annotations

from django.apps import AppConfig


class TimelineConfig(AppConfig):
    """Experimental. ``karni.timeline`` (label ``timeline``): TimelineEntry and TimelineLink.

    Add ``"karni.timeline"`` to ``INSTALLED_APPS`` next to ``karni.people``
    (its entries point at a person, ``karni.E461`` without it) and
    ``karni.outbox`` (entries from family events are delivered through it).

    ``ready()`` imports every app's ``events.py`` (unless
    ``KARNI_EVENTS_AUTODISCOVER`` is False), subscribes to each declared
    event that names a timeline title (:mod:`karni.timeline.subscribers`)
    and registers the people contract's erase hook, so an erased person's
    entries go with them.

    Override / escape hatch: ``KARNI_TIMELINE_FROM_EVENTS = False`` writes no
    entry from events, or subclass this config and point ``INSTALLED_APPS``
    at it (the label must stay ``timeline`` so the migrations apply).
    """

    name = "karni.timeline"
    label = "timeline"
    verbose_name = "Timeline"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from django.apps import apps
        from django.conf import settings

        from karni.timeline import checks, subscribers  # noqa: F401 - registers the checks

        if getattr(settings, "KARNI_EVENTS_AUTODISCOVER", True):
            from karni.events import autodiscover

            autodiscover()
        subscribers.connect()
        if apps.is_installed("karni.people"):
            from karni import people
            from karni.timeline.services import erase_person

            people.erase_hook("karni.timeline.entries", replace=True)(erase_person)
