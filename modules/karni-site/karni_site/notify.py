"""Email a saved row to the people a setting names: the notification a public form sends.

``karni make form ... --notify ENQUIRY_RECIPIENTS`` writes a queued listener
in the project that calls :func:`notify_recipients`::

    @on_created(Enquiry, queued=True)
    def notify_enquiry(enquiry: Enquiry) -> None:
        notify_recipients(
            enquiry,
            setting="ENQUIRY_RECIPIENTS",
            template="website/email/enquiry",
            reply_to=enquiry.email,
        )

``queued=True`` makes it run in a Celery worker once the row is committed,
so the visitor's request never waits for the mail server and a rolled-back
save sends nothing (docs/events.md). The function renders the project's own
templates, ``<template>_subject.txt`` and ``<template>_body.txt`` (and
``<template>_body.html`` when it exists), with:

* ``submission`` (also ``object``): the row.
* ``verbose_name``: the model's name for people (``"enquiry"``).
* ``fields``: ``(label, value)`` for each of the model's own fields.
* ``admin_path``: the row's admin change page (a path), or ``""``.
* ``frontend_url``: ``KARNI_FRONTEND_URL``, where the staff app runs.

The subject is collapsed to one line (no header injection from a visitor's
text). ``reply_to`` puts the visitor's address in ``Reply-To``, so staff
answer by replying.

Override / escape hatch: edit the templates. Pass ``context=`` for more
values, ``to=`` for fixed addresses, ``from_email=`` (else
``KARNI_SITE_NOTIFY_FROM``, else ``DEFAULT_FROM_EMAIL``). Or write the
listener's body yourself, since the listener is project code.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import Any

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import models
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string
from django.urls import NoReverseMatch, reverse
from karni.exceptions import KarniImproperlyConfigured

from karni_site import conf

__all__ = ["notification_context", "notify_recipients", "recipients"]

logger = logging.getLogger("karni_site")

#: BaseModel's own columns, left out of ``fields``.
_BOOKKEEPING = frozenset(
    {"id", "created_at", "updated_at", "deleted_at", "created_by", "updated_by"}
)


def recipients(setting: str) -> list[str]:
    """The addresses ``settings.<setting>`` holds: a list, or one comma-separated string.

    :raises KarniImproperlyConfigured: ``SITE023`` when the project does not define it.
    """
    if not hasattr(settings, setting):
        raise KarniImproperlyConfigured(
            f"karni_site.notify: the setting {setting} is not defined, so nobody can be told "
            f"about new rows. Add {setting} = env.list({setting!r}, default=[]) to "
            f"config/settings.py and {setting}=team@example.com to .env.",
            code="SITE023",
        )
    value = getattr(settings, setting)
    if isinstance(value, str):
        value = value.split(",")
    return [str(address).strip() for address in value or () if str(address).strip()]


def _display(instance: models.Model, model_field: models.Field[Any, Any]) -> str:
    if model_field.choices:
        getter = getattr(instance, f"get_{model_field.name}_display", None)
        if callable(getter):
            return str(getter())
    value = getattr(instance, model_field.name, None)
    if value is None:
        return ""
    if isinstance(model_field, models.BooleanField):
        return "yes" if value else "no"
    if isinstance(model_field, models.FileField):
        return str(value.name or "")
    return str(value)


def notification_context(instance: models.Model) -> dict[str, Any]:
    """What the templates get (see the module docstring)."""
    meta = instance._meta
    fields = [
        (str(model_field.verbose_name).capitalize(), _display(instance, model_field))
        for model_field in meta.concrete_fields
        if model_field.name not in _BOOKKEEPING and model_field.editable
    ]
    try:
        admin_path = reverse(f"admin:{meta.app_label}_{meta.model_name}_change", args=[instance.pk])
    except NoReverseMatch:
        admin_path = ""
    frontend = str(getattr(settings, "KARNI_FRONTEND_URL", "") or "").rstrip("/")
    return {
        "submission": instance,
        "object": instance,
        "verbose_name": str(meta.verbose_name),
        "fields": fields,
        "admin_path": admin_path,
        "frontend_url": frontend,
    }


def notify_recipients(
    instance: models.Model,
    *,
    template: str,
    setting: str | None = None,
    to: Iterable[str] | None = None,
    reply_to: str | None = None,
    context: Mapping[str, Any] | None = None,
    from_email: str | None = None,
) -> int:
    """Email ``instance`` to the addresses in ``settings.<setting>`` (or ``to``).

    Returns the number of messages sent: ``0`` when the setting holds no
    address (logged as a warning, so a project that has not set the
    recipients yet still saves every submission).
    """
    if (setting is None) == (to is None):
        raise KarniImproperlyConfigured(
            "notify_recipients() takes setting= (the name of a setting that lists the "
            "addresses) or to= (the addresses), exactly one.",
            code="SITE023",
        )
    addresses = recipients(setting) if setting is not None else [a for a in to or () if a]
    if not addresses:
        logger.warning(
            "karni_site.notify: no recipients for %s %s (%s is empty), so no email was sent.",
            instance._meta.label,
            instance.pk,
            setting or "to=",
        )
        return 0
    values = {**notification_context(instance), **dict(context or {})}
    subject = " ".join(render_to_string(f"{template}_subject.txt", values).split())
    body = render_to_string(f"{template}_body.txt", values)
    sender = from_email or conf.get("KARNI_SITE_NOTIFY_FROM") or None
    message = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=sender,
        to=addresses,
        reply_to=[reply_to] if reply_to else None,
    )
    try:
        html = render_to_string(f"{template}_body.html", values)
    except TemplateDoesNotExist:
        html = None
    if html is not None:
        message.attach_alternative(html, "text/html")
    return int(message.send())
