"""Experimental. An email from a project's own templates: the order confirmation, the reminder.

A business app sends mail at its own moments: an order is confirmed, a
booking is tomorrow, a refund went through. :func:`send_templated` renders
three templates a project can edit, and sends them with Django's mail
backend (the console in development)::

    from karni.mail import send_templated

    send_templated(
        "shop/email/order_confirmed",
        to=[order.email],
        context={"order": order},
    )

reads ``shop/email/order_confirmed_subject.txt`` (collapsed to one line, so
a value from a visitor can never add a header), ``..._body.txt`` and, when
it exists, ``..._body.html`` as the HTML part. Every template gets the
``context`` plus:

* ``frontend_url``: ``KARNI_FRONTEND_URL`` without its trailing slash, for
  links back into the app.

Send it from a listener once the data is committed, so a rolled-back
transaction sends nothing: ``@on_transition(Order, "status", to="paid",
queued=True)`` runs in a worker after the commit (docs/events.md), and
``transaction.on_commit(lambda: send_templated(...))`` does it in the request.

A message may carry a ``kind``, a stable name for what it is
(``commerce.order_paid``, ``shop.shipment_shipped``): it goes out in the
``X-Karni-Kind`` header, and a kind listed in ``KARNI_MAIL_DISABLED_KINDS``
is not sent at all, so a project switches one email off without code.

Demo data and imports should not mail anyone: inside ``with silenced():``
nothing is sent, including the messages that listeners queue with
``transaction.on_commit`` during the block (they run while the silence holds,
in the order they were queued).

Override / escape hatch: put a template of the same name earlier in
``TEMPLATES`` ``DIRS`` to change a message without code, pass
``from_email=`` (else ``DEFAULT_FROM_EMAIL``), ``reply_to=``, ``cc=`` or
``bcc=``, or build an :class:`~django.core.mail.EmailMultiAlternatives` with
:func:`render_templated` and send it yourself.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string

__all__ = [
    "silenced",
    "KIND_HEADER",
    "Rendered",
    "base_context",
    "kind_enabled",
    "render_templated",
    "send_templated",
]

#: The header a message's kind goes out in.
KIND_HEADER = "X-Karni-Kind"


@dataclass(frozen=True)
class Rendered:
    """Experimental. One message, rendered: its subject, its text and its HTML (or ``None``)."""

    subject: str
    text: str
    html: str | None


def base_context() -> dict[str, Any]:
    """Experimental. What every template gets besides the caller's context."""
    return {"frontend_url": str(getattr(settings, "KARNI_FRONTEND_URL", "") or "").rstrip("/")}


_SILENCE = [0]


def _hush() -> None:
    _SILENCE[0] += 1


def _speak() -> None:
    _SILENCE[0] = max(_SILENCE[0] - 1, 0)


@contextmanager
def silenced() -> Iterator[None]:
    """Experimental. Send nothing inside the block, nor from what it queues for the commit.

    The silence also covers the ``transaction.on_commit`` callbacks queued
    inside the block: one callback queued first starts it again at the commit,
    and one queued last ends it. A rolled-back transaction drops them all.
    """
    _hush()
    transaction.on_commit(_hush)
    try:
        yield
    finally:
        transaction.on_commit(_speak)
        _speak()


def kind_enabled(kind: str | None) -> bool:
    """Experimental. Whether a message of ``kind`` goes out (not in ``KARNI_MAIL_DISABLED_KINDS``)."""
    if not kind:
        return True
    return kind not in set(getattr(settings, "KARNI_MAIL_DISABLED_KINDS", None) or ())


def render_templated(template: str, context: Mapping[str, Any] | None = None) -> Rendered:
    """Experimental. ``<template>_subject.txt``, ``_body.txt`` and ``_body.html`` rendered.

    :raises TemplateDoesNotExist: when the subject or the text body is missing.
        The HTML body is optional.
    """
    values = {**base_context(), **dict(context or {})}
    subject = " ".join(render_to_string(f"{template}_subject.txt", values).split())
    text = render_to_string(f"{template}_body.txt", values)
    try:
        html: str | None = render_to_string(f"{template}_body.html", values)
    except TemplateDoesNotExist:
        html = None
    return Rendered(subject, text, html)


def send_templated(
    template: str,
    *,
    to: Iterable[str],
    context: Mapping[str, Any] | None = None,
    from_email: str | None = None,
    reply_to: Iterable[str] | None = None,
    cc: Iterable[str] | None = None,
    bcc: Iterable[str] | None = None,
    kind: str | None = None,
) -> int:
    """Experimental. Render ``template`` (see the module docstring) and send it to ``to``.

    Returns the number of messages sent: ``0`` when ``to`` holds no address,
    so a row without an email address never fails the code that saves it, and
    ``0`` when ``kind`` is switched off (``KARNI_MAIL_DISABLED_KINDS``).
    """
    addresses = [str(address).strip() for address in to if str(address or "").strip()]
    if not addresses or not kind_enabled(kind) or _SILENCE[0]:
        return 0
    rendered = render_templated(template, context)
    message = EmailMultiAlternatives(
        subject=rendered.subject,
        body=rendered.text,
        from_email=from_email or None,
        to=addresses,
        cc=list(cc) if cc else None,
        bcc=list(bcc) if bcc else None,
        reply_to=list(reply_to) if reply_to else None,
        headers={KIND_HEADER: kind} if kind else None,
    )
    if rendered.html is not None:
        message.attach_alternative(rendered.html, "text/html")
    return int(message.send())
