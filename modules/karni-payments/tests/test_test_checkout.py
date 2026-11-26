"""The test provider's checkout page: pay or decline in a browser."""

from __future__ import annotations

import pytest
from django.test import override_settings

from karni_payments.models import Payment, WebhookEvent
from karni_payments.test_checkout import enabled, settle
from tests.conftest import CANCEL_URL, SUCCESS_URL
from tests.test_api import CHECKOUT, _checkout_body

pytestmark = pytest.mark.django_db

PAGE_ON = override_settings(KARNI_PAYMENTS_TEST_CHECKOUT_PAGE=True)


def _checkout(api_client, user) -> tuple[Payment, str]:
    api_client.force_authenticate(user=user)
    response = api_client.post(CHECKOUT, _checkout_body(), format="json")
    assert response.status_code == 201, response.data
    return Payment.objects.get(), str(response.data["url"])


@PAGE_ON
def test_a_checkout_in_a_request_points_at_the_page_on_its_host(api_client, user) -> None:
    payment, url = _checkout(api_client, user)
    assert url == f"http://testserver/payments/test-checkout/{payment.checkout_session_id}/"
    assert payment.metadata["test_checkout"] == {
        "success_url": SUCCESS_URL,
        "cancel_url": CANCEL_URL,
    }


def test_the_page_is_off_without_debug_and_the_address_stays_imaginary(api_client, user) -> None:
    assert not enabled()
    payment, url = _checkout(api_client, user)
    assert url.startswith("https://checkout.test/pay/")
    assert "test_checkout" not in payment.metadata
    page = f"/payments/test-checkout/{payment.checkout_session_id}/"
    assert api_client.get(page).status_code == 404


@override_settings(DEBUG=True)
def test_debug_turns_the_page_on() -> None:
    assert enabled()


@override_settings(KARNI_PAYMENTS_PROVIDER="stripe", KARNI_PAYMENTS_TEST_CHECKOUT_PAGE=True)
def test_the_page_is_for_the_test_provider_only() -> None:
    assert not enabled()


@PAGE_ON
def test_the_page_shows_the_amount_and_both_choices(api_client, client, user) -> None:
    payment, url = _checkout(api_client, user)
    response = client.get(url.removeprefix("http://testserver"))
    assert response.status_code == 200
    body = response.content.decode()
    assert "42.00 USD" in body
    assert 'value="pay"' in body and 'value="decline"' in body


@PAGE_ON
def test_pay_settles_the_payment_through_the_webhook_pipeline_and_goes_back(
    api_client, client, user
) -> None:
    payment, url = _checkout(api_client, user)
    response = client.post(url.removeprefix("http://testserver"), {"outcome": "pay"})
    assert response.status_code == 302
    assert response["Location"] == SUCCESS_URL
    payment.refresh_from_db()
    assert payment.status == Payment.Status.SUCCEEDED
    event = WebhookEvent.objects.get()
    assert event.event_type == "payment.succeeded"
    assert event.processed_at is not None


@PAGE_ON
def test_decline_fails_the_payment_and_goes_to_the_cancel_url(api_client, client, user) -> None:
    payment, url = _checkout(api_client, user)
    response = client.post(url.removeprefix("http://testserver"), {"outcome": "decline"})
    assert response["Location"] == CANCEL_URL
    payment.refresh_from_db()
    assert payment.status == Payment.Status.FAILED


@PAGE_ON
def test_a_settled_payment_is_not_settled_again(api_client, client, user) -> None:
    payment, url = _checkout(api_client, user)
    settle(payment, "pay")
    client.post(url.removeprefix("http://testserver"), {"outcome": "decline"})
    payment.refresh_from_db()
    assert payment.status == Payment.Status.SUCCEEDED
    assert WebhookEvent.objects.count() == 1
    page = client.get(url.removeprefix("http://testserver")).content.decode()
    assert "This payment is succeeded." in page


@PAGE_ON
def test_an_unknown_outcome_or_session_is_refused(api_client, client, user) -> None:
    _payment, url = _checkout(api_client, user)
    assert client.post(url.removeprefix("http://testserver"), {"outcome": "x"}).status_code == 400
    assert client.get("/payments/test-checkout/test_cs_999/").status_code == 404


@PAGE_ON
def test_a_restarted_server_never_reuses_a_stored_session(api_client, user, make_payment) -> None:
    make_payment(checkout_session_id="test_cs_1", provider="test")
    make_payment(checkout_session_id="test_cs_2", provider="test")
    api_client.force_authenticate(user=user)
    response = api_client.post(CHECKOUT, _checkout_body(), format="json")
    assert response.status_code == 201, response.data
    assert str(response.data["url"]).endswith("/payments/test-checkout/test_cs_3/")
    assert Payment.objects.filter(checkout_session_id="test_cs_3").count() == 1


@PAGE_ON
def test_on_a_local_try_a_refund_goes_through_once_it_is_saved(
    api_client, client, user, django_capture_on_commit_callbacks
) -> None:
    from decimal import Decimal

    from karni_payments.models import Refund
    from karni_payments.services import create_refund

    payment, url = _checkout(api_client, user)
    client.post(url.removeprefix("http://testserver"), {"outcome": "pay"})
    payment.refresh_from_db()
    with django_capture_on_commit_callbacks(execute=True):
        refund = create_refund(payment, Decimal("1.00"), reason="a test")
    refund.refresh_from_db()
    assert refund.status == Refund.Status.SUCCEEDED


def test_without_the_page_a_refund_waits_for_its_webhook(user, make_payment) -> None:
    from decimal import Decimal

    from karni_payments.models import Refund
    from karni_payments.services import create_refund

    payment = make_payment(user=user, status=Payment.Status.SUCCEEDED)
    refund = create_refund(payment, Decimal("1.00"))
    assert refund.status == Refund.Status.PENDING
