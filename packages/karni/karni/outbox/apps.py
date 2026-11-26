"""App config for ``karni.outbox``: the tables family events are written to and delivered from."""

from __future__ import annotations

from django.apps import AppConfig


class KarniOutboxConfig(AppConfig):
    """``karni.outbox`` (label ``karni_outbox``).

    Add it to ``INSTALLED_APPS`` when a part publishes or subscribes to family
    events (:mod:`karni.events`): it brings the outbox, delivery and handled
    key tables, their admin, the delivery tasks and the beat schedules. The
    system checks of :mod:`karni.outbox.checks` run with or without it (Karni
    registers them), so a subscriber in a project without it is reported.
    """

    name = "karni.outbox"
    label = "karni_outbox"
    verbose_name = "Karni events"
    default_auto_field = "django.db.models.BigAutoField"
