"""Both sign-in methods in JWT mode, and the terms gate that follows either."""

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from karni.accounts.emails import InMemoryEmailBackend
from rest_framework.test import APIClient

from tests.idtokens import mint

pytestmark = pytest.mark.django_db

CUSTOMER = "oncology@example.com"


@pytest.fixture
def api(settings):
    settings.KARNI_ACCOUNTS_EMAIL_BACKEND = "karni.accounts.emails.InMemoryEmailBackend"
    settings.KARNI_SOCIAL_TOKEN_JWKS_FETCHER = "tests.idtokens.fake_fetch"
    settings.KARNI_EMAIL_OTP_SIGNUP = "approval"
    settings.KARNI_SOCIAL_TOKEN_SIGNUP = "approval"
    cache.clear()
    InMemoryEmailBackend.clear()
    return APIClient()


def client_id() -> str:
    return settings.KARNI_SOCIAL_TOKEN_PROVIDERS["google"]["client_ids"][0]


def send_code(api, address: str, on_commit) -> str:
    """Ask for a code and read it from the in-memory outbox (the mail goes out on commit)."""
    with on_commit(execute=True):
        assert api.post("/api/auth/otp/send/", {"email": address}, format="json").status_code == 200
    (email,) = [e for e in InMemoryEmailBackend.outbox if e.to.lower() == address]
    return email.context["code"]


def test_a_code_signs_in_and_the_terms_gate_comes_next(api, django_capture_on_commit_callbacks):
    code = send_code(api, CUSTOMER, django_capture_on_commit_callbacks)
    signed = api.post("/api/auth/otp/verify/", {"email": CUSTOMER, "code": code}, format="json")
    assert signed.status_code == 200 and {"access", "refresh"} <= set(signed.json())
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {signed.json()['access']}")
    refused = api.get("/api/trials/")
    assert refused.status_code == 403 and refused.json()["code"] == "E245"
    version = settings.KARNI_TERMS["version"]
    assert api.post("/api/auth/terms/accept/", {"version": version}, format="json").status_code in (
        200,
        201,
    )
    assert api.get("/api/trials/").status_code == 200


def test_a_wrong_code_is_refused(api, django_capture_on_commit_callbacks):
    send_code(api, CUSTOMER, django_capture_on_commit_callbacks)
    response = api.post(
        "/api/auth/otp/verify/", {"email": CUSTOMER, "code": "000000"}, format="json"
    )
    assert response.status_code == 401 and response.json()["code"] == "E235"


def test_a_new_address_waits_for_approval_and_sees_nothing(api, django_capture_on_commit_callbacks):
    code = send_code(api, "newcomer@example.com", django_capture_on_commit_callbacks)
    response = api.post(
        "/api/auth/otp/verify/", {"email": "newcomer@example.com", "code": code}, format="json"
    )
    assert response.status_code == 202 and response.json()["awaiting_approval"] is True
    assert not get_user_model().objects.get(email="newcomer@example.com").is_active


def test_a_google_id_token_signs_in_an_existing_customer(api):
    response = api.post(
        "/api/auth/social/google/", {"id_token": mint(client_id(), CUSTOMER)}, format="json"
    )
    assert response.status_code == 200, response.content
    assert response.json()["user"]["email"] == CUSTOMER and {"access", "refresh"} <= set(
        response.json()
    )
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")
    assert api.get("/api/trials/").status_code == 403  # the terms gate again


def test_a_new_google_account_waits_for_approval(api):
    response = api.post(
        "/api/auth/social/google/",
        {"id_token": mint(client_id(), "scout@example.com")},
        format="json",
    )
    assert response.status_code == 202 and response.json()["code"] == "E224"


def test_a_token_for_another_client_is_refused(api):
    response = api.post(
        "/api/auth/social/google/",
        {"id_token": mint("someone-elses-client", CUSTOMER)},
        format="json",
    )
    assert response.status_code == 401
    assert "access" not in response.json()


def test_terms_changed_mid_session_close_the_gate_again(client_for, settings):
    client = client_for(CUSTOMER)
    assert client.get("/api/trials/").status_code == 200
    settings.KARNI_TERMS = {**settings.KARNI_TERMS, "version": "2027-01"}
    cache.clear()
    assert client.get("/api/trials/").json()["code"] == "E245"
