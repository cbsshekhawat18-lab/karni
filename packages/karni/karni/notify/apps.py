"""App config for ``karni.notify``: the notifications contract (label ``notify``)."""

from __future__ import annotations

from django.apps import AppConfig


class NotifyConfig(AppConfig):
    """``karni.notify`` (label ``notify``): EmailTemplate, Notification, Choice,
    Unsubscribe.

    Add ``"karni.notify"`` to ``INSTALLED_APPS`` (``karni build`` does it for
    ``features: {notify: true}``, and a recipe whose ``recipe.toml`` requires
    ``notify>=1``) and run migrate.

    ``ready()`` registers the system checks. The email of every move that names
    a recipient (``moves.<state>.notify``) is declared as a message kind by
    ``karni/notify/messages.py`` when ``karni.mail`` reads each app's messages, so
    it is listed, edited and switched like a part's own.

    Override / escape hatch: subclass this config and point ``INSTALLED_APPS``
    at it (the label must stay ``notify`` so the migrations apply).
    """

    name = "karni.notify"
    label = "notify"
    verbose_name = "Notifications"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from karni.notify import checks  # noqa: F401 - registers the checks
