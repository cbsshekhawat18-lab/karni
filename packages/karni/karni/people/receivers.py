"""Experimental. The people contract's receivers, connected by ``PeopleConfig.ready()``.

* A user saved with a verified email (``email_verified``) is linked to the
  live person with that email, when there is one: every flow that
  proves an address sets that flag, so sign-up with verification, sign-in
  with an email code and a social sign-in with a verified address all link.
  A save that names its ``update_fields`` and touches neither the email nor
  the flag (a sign-in stamping ``last_login``) costs nothing.
* A new Person or Organisation, from any part, the admin or a seed run,
  publishes ``people.person.created`` or ``people.organisation.created``.

Override / escape hatch: ``KARNI_PEOPLE_LINK_ON_VERIFY = False`` turns the
account link off (call :func:`karni.people.link_account` yourself).
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save

__all__ = ["connect"]

_UID = "karni.people."
_LINK_FIELDS = frozenset({"email", "email_verified"})


def _link_verified(sender: Any, instance: Any, raw: bool = False, **kwargs: Any) -> None:
    if raw or not getattr(settings, "KARNI_PEOPLE_LINK_ON_VERIFY", True):
        return
    if not getattr(instance, "email_verified", False):
        return
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and not (_LINK_FIELDS & set(update_fields)):
        return
    from karni.people.services import link_account

    link_account(instance, strict=False, create=False)


def _announce(sender: Any, instance: Any, created: bool, raw: bool = False, **kwargs: Any) -> None:
    if not created or raw:
        return
    from karni.people.events import publish
    from karni.people.models import Person

    if sender is Person:
        publish("people.person.created", subject=instance, person=instance, source=instance.source)
    else:
        publish("people.organisation.created", subject=instance, source=instance.source)


def connect() -> None:
    """Connect the receivers (idempotent through ``dispatch_uid``)."""
    from karni.people.models import Organisation, Person

    post_save.connect(
        _link_verified, sender=get_user_model(), dispatch_uid=_UID + "link", weak=False
    )
    post_save.connect(_announce, sender=Person, dispatch_uid=_UID + "person", weak=False)
    post_save.connect(
        _announce, sender=Organisation, dispatch_uid=_UID + "organisation", weak=False
    )
