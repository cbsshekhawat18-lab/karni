"""Experimental. What happens to a payment or a refund, as signals any app can receive.

An app that sells through karni-payments (an order, a booking, an
enrolment) reacts to a payment without reading the webhook itself::

    from django.dispatch import receiver
    from karni_payments.events import payment_status_changed


    @receiver(payment_status_changed)
    def settle(sender, payment, source, target, **kwargs):
        if target == "succeeded":
            ...

* :data:`payment_status_changed`: a payment moved from ``source`` to
  ``target`` (``pending`` to ``succeeded``, ``failed``, ``canceled``,
  ``succeeded`` to ``partially_refunded`` or ``refunded``). Sent by the
  webhook state machine, inside its transaction, after the row is saved.
* :data:`refund_created`: a refund was asked for (``create_refund``), after
  the provider took it.
* :data:`refund_status_changed`: a refund moved from ``source`` to ``target``
  (``pending`` to ``succeeded`` or ``failed``).

``sender`` is the model class (``Payment`` or ``Refund``). A receiver that
raises inside the webhook's transaction undoes the change, and the webhook
task retries. Karni's autodiscovery imports ``<app>/listeners.py``, the
place for these receivers (docs/events.md).

Override / escape hatch: these are plain :class:`django.dispatch.Signal`
objects. A project that replaces the state machine
(``KARNI_PAYMENTS_EVENT_HANDLER``) sends them from its own handler with
:func:`announce`.
"""

from __future__ import annotations

from typing import Any

from django.dispatch import Signal

__all__ = ["announce", "payment_status_changed", "refund_created", "refund_status_changed"]

#: A payment's status moved: ``payment``, ``source``, ``target``.
payment_status_changed = Signal()
#: A refund was created: ``refund``, ``payment``.
refund_created = Signal()
#: A refund's status moved: ``refund``, ``payment``, ``source``, ``target``.
refund_status_changed = Signal()


def announce(row: Any, source: str) -> None:
    """Send the status signal of ``row`` (a Payment or a Refund) that moved from ``source``."""
    from karni_payments.models import Payment, Refund

    if isinstance(row, Payment):
        payment_status_changed.send(
            sender=Payment, payment=row, source=source, target=str(row.status)
        )
    elif isinstance(row, Refund):
        refund_status_changed.send(
            sender=Refund,
            refund=row,
            payment=row.payment,
            source=source,
            target=str(row.status),
        )
