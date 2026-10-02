"""API surface (amendment G1): read-only resources, actions, roles, scoping."""

from __future__ import annotations

from decimal import Decimal

import pytest

from karni_payments.models import Payment, Refund
from tests.conftest import CANCEL_URL, SUCCESS_URL

pytestmark = pytest.mark.django_db

PAYMENTS = "/api/payments/"
CHECKOUT = "/api/payments/checkout/"
REFUNDS = "/api/refunds/"


def _checkout_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "amount": "42.00",
        "success_url": SUCCESS_URL,
        "cancel_url": CANCEL_URL,
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# Authentication + owner scoping (payments-admin bypass)
# ---------------------------------------------------------------------------


def test_anonymous_cannot_read_payments(api_client) -> None:
    assert api_client.get(PAYMENTS).status_code == 401


def test_payments_list_is_owner_scoped(api_client, user, other_user, make_payment) -> None:
    make_payment()
    make_payment()
    make_payment(user=other_user)
    api_client.force_authenticate(user=user)
    response = api_client.get(PAYMENTS)
    assert response.status_code == 200
    assert response.data["count"] == 2


def test_payments_admin_bypasses_owner_scoping(
    api_client, user, other_user, admin_user, make_payment
) -> None:
    make_payment()
    make_payment(user=other_user)
    api_client.force_authenticate(user=admin_user)
    response = api_client.get(PAYMENTS)
    assert response.status_code == 200
    assert response.data["count"] == 2


def test_detail_of_another_users_payment_is_404(api_client, other_user, user, make_payment) -> None:
    payment = make_payment(user=other_user)
    api_client.force_authenticate(user=user)
    assert api_client.get(f"{PAYMENTS}{payment.pk}/").status_code == 404


def test_payments_admin_retrieves_any_users_payment(
    api_client, other_user, admin_user, make_payment
) -> None:
    payment = make_payment(user=other_user)
    api_client.force_authenticate(user=admin_user)
    assert api_client.get(f"{PAYMENTS}{payment.pk}/").status_code == 200


def test_anonymous_refund_is_401(api_client, make_payment) -> None:
    payment = make_payment(status=Payment.Status.SUCCEEDED)
    assert api_client.post(f"{PAYMENTS}{payment.pk}/refund/", {}, format="json").status_code == 401
    assert payment.refunds.count() == 0


def test_payment_payload_hides_checkout_internals(api_client, user, make_payment) -> None:
    make_payment(checkout_session_id="test_cs_secret")
    api_client.force_authenticate(user=user)
    [row] = api_client.get(PAYMENTS).data["results"]
    assert "checkout_session_id" not in row
    assert row["status"] == "pending"


# ---------------------------------------------------------------------------
# Read-only resources (writes answer 405)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["post"])
def test_payment_create_is_method_not_allowed(api_client, user, method: str) -> None:
    api_client.force_authenticate(user=user)
    response = getattr(api_client, method)(PAYMENTS, {"amount": "1.00"}, format="json")
    assert response.status_code == 405


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_payment_mutations_are_method_not_allowed(
    api_client, user, make_payment, method: str
) -> None:
    payment = make_payment()
    api_client.force_authenticate(user=user)
    response = getattr(api_client, method)(f"{PAYMENTS}{payment.pk}/", {}, format="json")
    assert response.status_code == 405


# ---------------------------------------------------------------------------
# Checkout action (detail=False)
# ---------------------------------------------------------------------------


def test_checkout_requires_authentication(api_client) -> None:
    assert api_client.post(CHECKOUT, _checkout_body(), format="json").status_code == 401


def test_checkout_creates_payment_and_returns_redirect_url(api_client, user) -> None:
    api_client.force_authenticate(user=user)
    response = api_client.post(CHECKOUT, _checkout_body(), format="json")
    assert response.status_code == 201
    payment = Payment.objects.get()
    assert payment.user == user
    assert payment.status == Payment.Status.PENDING
    assert response.data["payment_id"] == str(payment.pk)
    assert response.data["session_id"] == "test_cs_1"
    assert response.data["url"].startswith("https://checkout.test/")


def test_checkout_rejects_bad_input(api_client, user) -> None:
    api_client.force_authenticate(user=user)
    assert api_client.post(CHECKOUT, _checkout_body(amount="-5"), format="json").status_code == 400
    assert (
        api_client.post(
            CHECKOUT, _checkout_body(success_url="https://evil.example/x"), format="json"
        ).status_code
        == 400
    )
    assert Payment.objects.count() == 0


# ---------------------------------------------------------------------------
# Refund action (detail=True, role-gated)
# ---------------------------------------------------------------------------


def test_refund_requires_the_payments_admin_role(api_client, user, make_payment) -> None:
    payment = make_payment(status=Payment.Status.SUCCEEDED)
    api_client.force_authenticate(user=user)
    response = api_client.post(f"{PAYMENTS}{payment.pk}/refund/", {}, format="json")
    assert response.status_code == 403
    assert payment.refunds.count() == 0


def test_admin_can_refund_any_users_payment(api_client, admin_user, make_payment) -> None:
    payment = make_payment(status=Payment.Status.SUCCEEDED)  # owned by `user`
    api_client.force_authenticate(user=admin_user)
    response = api_client.post(f"{PAYMENTS}{payment.pk}/refund/", {}, format="json")
    assert response.status_code == 201
    refund = payment.refunds.get()
    assert refund.amount == Decimal("100.00")
    assert response.data["status"] == "pending"
    assert response.data["provider_refund_id"] == "test_re_1"


def test_partial_refund_with_amount_and_reason(api_client, admin_user, make_payment) -> None:
    payment = make_payment(status=Payment.Status.SUCCEEDED)
    api_client.force_authenticate(user=admin_user)
    response = api_client.post(
        f"{PAYMENTS}{payment.pk}/refund/",
        {"amount": "25.00", "reason": "goodwill"},
        format="json",
    )
    assert response.status_code == 201
    assert response.data["amount"] == "25.00"
    assert response.data["reason"] == "goodwill"


def test_over_refund_is_a_400(api_client, admin_user, make_payment) -> None:
    payment = make_payment(status=Payment.Status.SUCCEEDED)
    api_client.force_authenticate(user=admin_user)
    response = api_client.post(
        f"{PAYMENTS}{payment.pk}/refund/", {"amount": "999.00"}, format="json"
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# RefundViewSet (read-only, role-gated)
# ---------------------------------------------------------------------------


def test_refund_list_requires_the_role(api_client, user, make_payment) -> None:
    payment = make_payment()
    Refund.objects.create(payment=payment, amount=Decimal("10.00"))
    api_client.force_authenticate(user=user)
    assert api_client.get(REFUNDS).status_code == 403


def test_admin_lists_refunds(api_client, admin_user, make_payment) -> None:
    payment = make_payment()
    Refund.objects.create(payment=payment, amount=Decimal("10.00"))
    api_client.force_authenticate(user=admin_user)
    response = api_client.get(REFUNDS)
    assert response.status_code == 200
    assert response.data["count"] == 1


def test_refund_writes_are_method_not_allowed(api_client, admin_user, make_payment) -> None:
    payment = make_payment()
    refund = Refund.objects.create(payment=payment, amount=Decimal("10.00"))
    api_client.force_authenticate(user=admin_user)
    assert api_client.post(REFUNDS, {}, format="json").status_code == 405
    assert api_client.delete(f"{REFUNDS}{refund.pk}/").status_code == 405
