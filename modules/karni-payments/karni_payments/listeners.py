"""Experimental. karni-payments' family events: declared here, published when a status moves.

Any part reacts to a payment by name, without importing this module::

    from karni.events import Event, subscribe


    @subscribe("payments.payment.succeeded", version=1)
    def thank_buyer(event: Event) -> None:
        ...  # event["payment"], event["amount"] (a decimal string), event["currency"]

* ``payments.payment.succeeded``: the provider confirmed a payment
  (``payment``, ``amount``, ``currency``).
* ``payments.payment.failed``: the provider refused it (``payment``,
  ``amount``).
* ``payments.refund.succeeded``: a refund went through (``refund``,
  ``payment``, ``amount``).

They are published from the payment's and the refund's ``post_save``, in the
transaction of the save that moved the status (the webhook task's), so any
code path that saves a new status publishes once: the state machine, a
project's own ``KARNI_PAYMENTS_EVENT_HANDLER``, the admin. A row created with
the status already set publishes too. ``QuerySet.update()`` sends no signal
and publishes nothing, and a row loaded with ``status`` deferred publishes
nothing when saved. The subject is the payment (or the refund), the actor
the current user (none in a webhook), and the person is left empty.

A part that must act inside the payment's own transaction (an order marked
paid) keeps using a plain signal: the bus delivers after the commit, in a
worker.

Override / escape hatch: disconnect :func:`publish_payment` or
:func:`publish_refund` (``post_save.disconnect(..., sender=Payment)``) and
publish these events yourself with :func:`karni.events.publish`.
"""

from __future__ import annotations

from typing import Any, Final

from django.db.models.signals import post_init, post_save
from django.dispatch import receiver
from karni.events import declare, publish

from karni_payments.models import Payment, Refund

__all__ = ["publish_payment", "publish_refund", "remember_status"]

declare(
    "payments.payment.succeeded",
    version=1,
    fields={
        "payment": "the payment's id",
        "amount": "the amount paid, a decimal string",
        "currency": "the ISO 4217 code, lower case",
    },
    describe="The provider confirmed a payment.",
)
declare(
    "payments.payment.failed",
    version=1,
    fields={"payment": "the payment's id", "amount": "the amount asked, a decimal string"},
    describe="The provider refused a payment.",
)
declare(
    "payments.refund.succeeded",
    version=1,
    fields={
        "refund": "the refund's id",
        "payment": "the refunded payment's id",
        "amount": "the amount refunded, a decimal string",
    },
    describe="A refund went through.",
)

#: Where the status a row was loaded with is kept, to see that a save moved it.
_LOADED: Final = "_karni_payments_loaded_status"
_UNKNOWN: Final = object()


@receiver(post_init, sender=Payment, dispatch_uid="karni_payments.listeners.payment_loaded")
@receiver(post_init, sender=Refund, dispatch_uid="karni_payments.listeners.refund_loaded")
def remember_status(sender: Any, instance: Payment | Refund, **kwargs: Any) -> None:
    """Keep the status the row was loaded or built with (unknown when it is deferred)."""
    instance.__dict__[_LOADED] = instance.__dict__.get("status", _UNKNOWN)


def _moved(instance: Payment | Refund, created: bool) -> str | None:
    """The new status when this save moved it, else None. Remembers it for the next save."""
    current = instance.__dict__.get("status", _UNKNOWN)
    previous = None if created else instance.__dict__.get(_LOADED, _UNKNOWN)
    instance.__dict__[_LOADED] = current
    if current is _UNKNOWN or previous is _UNKNOWN or current == previous:
        return None
    return str(current)


@receiver(post_save, sender=Payment, dispatch_uid="karni_payments.listeners.payment_saved")
def publish_payment(
    sender: Any, instance: Payment, created: bool = False, raw: bool = False, **kwargs: Any
) -> None:
    """``payments.payment.succeeded`` or ``.failed`` when a save moved the status there."""
    moved = None if raw else _moved(instance, created)
    using = kwargs.get("using")
    if moved == Payment.Status.SUCCEEDED:
        publish(
            "payments.payment.succeeded",
            subject=instance,
            using=using,
            payment=str(instance.pk),
            amount=str(instance.amount),
            currency=instance.currency,
        )
    elif moved == Payment.Status.FAILED:
        publish(
            "payments.payment.failed",
            subject=instance,
            using=using,
            payment=str(instance.pk),
            amount=str(instance.amount),
        )


@receiver(post_save, sender=Refund, dispatch_uid="karni_payments.listeners.refund_saved")
def publish_refund(
    sender: Any, instance: Refund, created: bool = False, raw: bool = False, **kwargs: Any
) -> None:
    """``payments.refund.succeeded`` when a save moved the refund's status there."""
    moved = None if raw else _moved(instance, created)
    if moved == Refund.Status.SUCCEEDED:
        publish(
            "payments.refund.succeeded",
            subject=instance,
            using=kwargs.get("using"),
            refund=str(instance.pk),
            payment=str(instance.payment_id),
            amount=str(instance.amount),
        )
