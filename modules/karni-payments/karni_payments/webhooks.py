"""The provider webhook endpoint — receive, verify, persist, enqueue.

**Nothing state-changing happens in the request cycle** (amendment G3): the
view verifies the signature, stores the delivery as a
:class:`~karni_payments.models.WebhookEvent` in its own
``transaction.atomic`` block, and enqueues the Celery task via
``transaction.on_commit``. All payment/refund state changes run in
:mod:`karni_payments.tasks`.

Delivery semantics:

* bad signature → HTTP 400, **nothing persisted**, one structured warning
  log (provider, IP, reason);
* first delivery → row created, task enqueued on commit, HTTP 200;
* redelivery of a processed event → HTTP 200, no-op;
* redelivery with ``processed_at`` still NULL → task **re-enqueued** (this
  recovers events whose retries were exhausted; safe under the task's
  lock-and-skip).

Override / escape hatch: this is a plain function view — wrap it (or mount
your own URL pattern before the module's) for extra concerns like IP
allowlisting; swap the state machine itself via
``KARNI_PAYMENTS_EVENT_HANDLER``.
"""

from __future__ import annotations

import logging

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from karni_payments.models import WebhookEvent
from karni_payments.providers.base import WebhookVerificationError, get_provider_by_name
from karni_payments.tasks import process_webhook_event

__all__ = ["webhook"]

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def webhook(request: HttpRequest, provider: str) -> HttpResponse:
    """Receive one provider webhook delivery (``POST webhook/<provider>/``)."""
    try:
        provider_instance = get_provider_by_name(provider)
    except (LookupError, ImproperlyConfigured) as exc:
        raise Http404(f"Unknown payment provider {provider!r}.") from exc

    try:
        parsed = provider_instance.parse_webhook(request.body, request.headers)
    except WebhookVerificationError as exc:
        logger.warning(
            "Payment webhook rejected: provider=%s ip=%s reason=%s",
            provider_instance.name,
            request.META.get("REMOTE_ADDR", ""),
            exc,
        )
        return HttpResponse(status=400)
    if not parsed.event_id:
        logger.warning(
            "Payment webhook rejected: provider=%s ip=%s reason=%s",
            provider_instance.name,
            request.META.get("REMOTE_ADDR", ""),
            "delivery carries no event id",
        )
        return HttpResponse(status=400)

    # The view's own transaction (never the caller's): the row must be
    # committed — and the task enqueued — even if the surrounding request
    # does more work later.
    with transaction.atomic():
        event, created = WebhookEvent.objects.get_or_create(
            provider=provider_instance.name,
            event_id=parsed.event_id,
            defaults={"event_type": parsed.event_type, "payload": parsed.raw},
        )
        if created or event.processed_at is None:
            event_pk = str(event.pk)
            transaction.on_commit(lambda: process_webhook_event.delay(event_pk))
    return HttpResponse("ok")
