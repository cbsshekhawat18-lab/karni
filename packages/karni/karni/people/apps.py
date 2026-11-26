"""App config for ``karni.people``: the people contract (label ``people``)."""

from __future__ import annotations

from django.apps import AppConfig


class PeopleConfig(AppConfig):
    """``karni.people`` (label ``people``): Person, Organisation, Membership, Address.

    Installed by ``KARNI_PEOPLE = True`` (which ``karni_settings()`` turns into
    an ``INSTALLED_APPS`` entry, and which ``karni build`` writes when the spec
    points at ``people.Person``), or by listing ``"karni.people"`` yourself.

    ``ready()`` connects the account link (a user whose email is verified gets
    the person with that email), announces new people and organisations
    (:mod:`karni.people.events`) and imports every installed app's
    ``people.py``, where a part declares its person facts, merge hooks and
    erase hooks (:mod:`karni.people.registry`).

    Override / escape hatch: ``KARNI_PEOPLE_LINK_ON_VERIFY = False`` leaves
    accounts unlinked until a part calls :func:`karni.people.link_account`;
    ``KARNI_PEOPLE_AUTODISCOVER = False`` stops the ``people.py`` import; or
    subclass this config and point ``INSTALLED_APPS`` at it (the label must
    stay ``people`` so the migrations apply).
    """

    name = "karni.people"
    label = "people"
    verbose_name = "People"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from django.conf import settings

        from karni.people import receivers, registry

        receivers.connect()
        registry.register_builtin_hooks()
        if getattr(settings, "KARNI_PEOPLE_AUTODISCOVER", True):
            registry.autodiscover()
