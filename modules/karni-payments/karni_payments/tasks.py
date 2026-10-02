"""Celery task applying stored webhook events to payment state.

Pipeline guarantees (amendment G3):

* the row lock (``select_for_update``), the state machine
  (``KARNI_PAYMENTS_EVENT_HANDLER``) and the ``processed_at`` stamp all run
  in **one** ``transaction.atomic`` block — a crash mid-way leaves the event
  unprocessed and re-runnable;
* an already-processed event is skipped under the lock (idempotent against
  duplicate deliveries and re-enqueues);
* on failure the error text is written **outside** that transaction (the
  rollback must not erase it) and the exception re-raises into Celery's
  retry policy (3 retries, exponential backoff);
* an event matching no payment raises — retries find the payment once the
  checkout transaction lands; such events are never marked processed.

The lock is effective on PostgreSQL; sqlite ignores ``select_for_update``
but serialises writers anyway, so tests on sqlite assert behaviour, not
concurrency.

Override / escape hatch: swap the state machine via
``KARNI_PAYMENTS_EVENT_HANDLER`` (dotted path, default
``karni_payments.services.apply_event``); adjust retry policy by subclassing
or re-registering the task under your own name and pointing your queue at it.
"""

from __future__ import annotations

from celery import shared_task
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from karni_payments import conf
from karni_payments.models import WebhookEvent

__all__ = ["process_webhook_event"]


@shared_task(
    name="karni_payments.tasks.process_webhook_event",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def process_webhook_event(event_pk: str) -> None:
    """Apply one stored :class:`~karni_payments.models.WebhookEvent`.

    See the module docstring for the transactional guarantees. The handler
    may write a "no-op:" note into ``event.error``; the final save persists
    both the note and the ``processed_at`` stamp together.
    """
    try:
        with transaction.atomic():
            event = WebhookEvent.objects.select_for_update().get(pk=event_pk)
            if event.processed_at is not None:
                return
            handler = import_string(conf.get("KARNI_PAYMENTS_EVENT_HANDLER"))
            handler(event)
            event.processed_at = timezone.now()
            event.save(update_fields=["processed_at", "error", "updated_at"])
    except Exception as exc:
        # Written outside the (rolled-back) transaction so the text survives.
        WebhookEvent.objects.filter(pk=event_pk).update(error=f"{type(exc).__name__}: {exc}")
        raise
