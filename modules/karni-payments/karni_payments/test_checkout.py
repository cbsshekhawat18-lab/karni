"""The test provider's checkout page: pay or decline a test payment in a browser.

With ``KARNI_PAYMENTS_PROVIDER = "test"``, a real gateway is never called,
and in a project's development server or a demo there is no gateway page to
send the customer to. While ``KARNI_PAYMENTS_TEST_CHECKOUT_PAGE`` is on (by
default, while ``DEBUG`` is), :class:`~karni_payments.providers.test.TestProvider`
gives each checkout started in a request the address of this page on that
request's host::

    GET  /payments/test-checkout/<session>/    the amount, Pay and Decline
    POST /payments/test-checkout/<session>/    outcome=pay or outcome=decline

A choice is applied the way a provider's webhook is: a signed test event is
stored as a :class:`~karni_payments.models.WebhookEvent` and processed by
the same state machine (``KARNI_PAYMENTS_EVENT_HANDLER``), at once, in the
request, so no worker has to run. Then the page sends the person to the
checkout's ``success_url`` (paid) or ``cancel_url`` (declined). The page
answers 404 for any other provider, or while the setting is off.

Override / escape hatch: replace the template
``karni_payments/test_checkout.html`` in your project's templates, set
``KARNI_PAYMENTS_TEST_CHECKOUT_PAGE = False`` to keep the imaginary address,
or mount your own view at the same path before ``karni_payments.urls``.
"""

from __future__ import annotations

import uuid
from typing import Any

from django.conf import settings
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse
from django.views.decorators.http import require_http_methods
from karni.tracing import get_origin

from karni_payments import conf
from karni_payments.models import Payment, WebhookEvent

__all__ = ["OUTCOMES", "confirm_refund", "enabled", "page_url", "settle", "view"]

#: What the page's buttons send: the test event each one stores.
OUTCOMES: dict[str, tuple[str, str]] = {
    "pay": ("payment.succeeded", "succeeded"),
    "decline": ("payment.failed", "failed"),
}


def enabled() -> bool:
    """Whether the page is served: the test provider, and the setting on (or ``DEBUG``)."""
    if str(conf.get("KARNI_PAYMENTS_PROVIDER")) != "test":
        return False
    chosen = conf.get("KARNI_PAYMENTS_TEST_CHECKOUT_PAGE")
    return bool(settings.DEBUG) if chosen is None else bool(chosen)


def page_url(session_id: str) -> str | None:
    """The page's full address for ``session_id``, or ``None``.

    ``None`` while the page is off, outside a request (the host is not
    known), or when the project does not include ``karni_payments.urls``.
    """
    if not enabled():
        return None
    origin = get_origin()
    if not origin:
        return None
    try:
        path = reverse("karni_payments:test_checkout", kwargs={"session": session_id})
    except NoReverseMatch:
        return None
    return f"{origin}{path}"


def _payment(session: str) -> Payment:
    if not enabled():
        raise Http404("The test checkout page is off.")
    found = Payment.objects.filter(provider="test", checkout_session_id=session).first()
    if found is None:
        raise Http404("No test payment has this checkout session.")
    return found


def _back(payment: Payment, outcome: str) -> str:
    from karni_payments.providers.test import PAGE_KEY

    urls: dict[str, Any] = dict(payment.metadata.get(PAGE_KEY) or {})
    return str(urls.get("success_url" if outcome == "pay" else "cancel_url") or "")


def settle(payment: Payment, outcome: str) -> WebhookEvent:
    """Apply ``outcome`` (``pay`` or ``decline``) to ``payment`` as a test webhook would.

    The event is stored and processed by ``KARNI_PAYMENTS_EVENT_HANDLER``
    in this call, so the payment's status (and every listener on it) has
    moved when it returns.
    """
    from karni_payments.providers.test import TestProvider
    from karni_payments.tasks import process_webhook_event

    event_type, status = OUTCOMES[outcome]
    payload = {
        "id": f"evt_page_{uuid.uuid4().hex}",
        "type": event_type,
        "status": status,
        "checkout_session_id": payment.checkout_session_id,
    }
    parsed = TestProvider().map_event(str(payload["id"]), event_type, payload)
    with transaction.atomic():
        event = WebhookEvent.objects.create(
            provider=TestProvider.name,
            event_id=parsed.event_id,
            event_type=parsed.event_type,
            payload=parsed.raw,
        )
    process_webhook_event(str(event.pk))
    event.refresh_from_db()
    return event


def confirm_refund(payment: Payment) -> WebhookEvent:
    """The test provider's word that a refund of ``payment`` went through.

    While the test checkout page is served (:func:`enabled`), the test provider
    confirms each refund this way once its transaction commits, so a refund
    made on a local try settles as a real provider's webhook would settle it.
    """
    from karni_payments.providers.test import TestProvider
    from karni_payments.tasks import process_webhook_event

    payload = {
        "id": f"evt_refund_{uuid.uuid4().hex}",
        "type": "refund",
        "status": "refund_succeeded",
        "checkout_session_id": payment.checkout_session_id,
    }
    parsed = TestProvider().map_event(str(payload["id"]), "refund", payload)
    with transaction.atomic():
        event = WebhookEvent.objects.create(
            provider=TestProvider.name,
            event_id=parsed.event_id,
            event_type=parsed.event_type,
            payload=parsed.raw,
        )
    process_webhook_event(str(event.pk))
    event.refresh_from_db()
    return event


@require_http_methods(["GET", "POST"])
def view(request: HttpRequest, session: str) -> HttpResponse:
    """The page (``GET``), and a choice (``POST`` with ``outcome``)."""
    payment = _payment(session)
    if request.method == "POST":
        outcome = str(request.POST.get("outcome", ""))
        if outcome not in OUTCOMES:
            return HttpResponse("outcome must be pay or decline.", status=400)
        if payment.status == Payment.Status.PENDING:
            settle(payment, outcome)
        back = _back(payment, outcome)
        if back:
            return HttpResponseRedirect(back)
        payment.refresh_from_db()
    context = {
        "payment": payment,
        "open": payment.status == Payment.Status.PENDING,
        "amount": f"{payment.amount:.2f}",
        "currency": payment.currency.upper(),
        "back": _back(payment, "pay"),
    }
    return render(request, "karni_payments/test_checkout.html", context)
