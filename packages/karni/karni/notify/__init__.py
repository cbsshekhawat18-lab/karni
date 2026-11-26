"""Experimental. The notifications contract: message kinds, edited emails, the inbox, switches.

A project that holds several parts sends one set of messages: an order is
paid, a booking is confirmed, a deal is assigned. Each part declares the
messages it sends in its ``messages.py`` with ``karni.mail.register_kind``
(the merge fields, transactional or marketing, the channels), and sends them
with one call::

    from karni import notify

    notify.send("crm.deal_assigned", to=[deal.owner], context={"deal": deal, "link": url})

``karni.mail.send_templated(..., kind=...)`` goes through the same path, so a
part that already sends with it keeps its call. Add ``"karni.notify"`` to
``INSTALLED_APPS`` (``features: {notify: true}`` in karni.yaml, or a recipe that
requires ``notify>=1``). What it gives:

* **Message kinds** on ``karni.mail``: an email, the recipient's inbox in the
  app, or both (``channels=``), each listed in Settings, Emails.
* **Emails a business edits**: :class:`~karni.notify.models.EmailTemplate`,
  ``/api/email-templates/``, rendered by the restricted engine. The default
  ``KARNI_MAIL_SOURCE`` is :class:`~karni.notify.source.NotifySource`.
* **The inbox**: :class:`~karni.notify.models.Notification`, ``/api/inbox/``
  (list, unread count, mark read, mark all read), pruned after
  ``KARNI_NOTIFY_RETENTION_DAYS``.
* **Switches**: each kind in Settings, Emails (the preferences contract), and
  each person's own (:func:`choose`, ``/api/inbox/choices/``).
* **Unsubscribe**: a marketing kind carries a signed link and the
  ``List-Unsubscribe`` headers, and an address that left it gets no more of it
  from any part (:func:`unsubscribe`, ``/api/notify/unsubscribe/``).
* **One sender**: the From and Reply-To of Settings, Details.

The contract is versioned: :data:`CONTRACT`. See docs/notify.md.

The names are imported lazily (PEP 562): this package is imported while the
app registry is still loading, before its models exist.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from karni.notify.services import (
        Recipient,
        Sent,
        choices,
        choose,
        holders,
        installed,
        mark_read,
        mark_unread,
        on_event,
        prune,
        receives,
        recipients,
        resubscribe,
        send,
        unread_count,
        unsubscribe,
        unsubscribe_url,
        unsubscribed,
    )

#: The version of the notifications contract. A breaking change raises it.
CONTRACT: Final = 1

__all__ = [
    "CONTRACT",
    "Recipient",
    "Sent",
    "choices",
    "choose",
    "holders",
    "installed",
    "mark_read",
    "mark_unread",
    "on_event",
    "prune",
    "receives",
    "recipients",
    "resubscribe",
    "send",
    "unread_count",
    "unsubscribe",
    "unsubscribe_url",
    "unsubscribed",
]

_LAZY: Final[dict[str, str]] = {name: "karni.notify.services" for name in __all__[1:]}


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(module), name)


def __dir__() -> list[str]:
    return sorted([*__all__, *globals()])
