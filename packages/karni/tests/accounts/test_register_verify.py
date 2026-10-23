"""Registration and email-verification flow tests.

Covers: registration creates an unverified user and sends the verification
email through the configured accounts email backend *on commit* (amendment
A7, observed with ``django_capture_on_commit_callbacks``), the verify flow,
replay protection, resend (auth-required per amendment A9), and the accepted
duplicate-registration 400.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import ModuleType

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import URLPattern, include, path
from pytest_django import DjangoCaptureOnCommitCallbacks, Settings
from rest_framework.test import APIClient

from karni.accounts.emails import InMemoryEmailBackend
from karni.accounts.urls import build_urlpatterns
from karni.testing.schema import generate_schema

pytestmark = pytest.mark.django_db

REGISTER_URL = "/api/auth/register/"
VERIFY_URL = "/api/auth/email/verify/"
RESEND_URL = "/api/auth/email/verify/resend/"

EMAIL = "vera@example.com"
PASSWORD = "sturdy-p4ssword-91"


@pytest.fixture(autouse=True)
def _in_memory_email_backend(settings: Settings) -> Iterator[None]:
    """Route accounts mail into the in-memory outbox and keep it clean."""
    settings.KARNI_ACCOUNTS_EMAIL_BACKEND = "karni.accounts.emails.InMemoryEmailBackend"
    InMemoryEmailBackend.clear()
    yield
    InMemoryEmailBackend.clear()


@pytest.fixture(autouse=True)
def _fresh_throttle_state() -> Iterator[None]:
    """Scoped auth throttles count hits in the default cache; isolate tests."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


def _register(
    api_client: APIClient,
    capture: DjangoCaptureOnCommitCallbacks,
    email: str = EMAIL,
    password: str = PASSWORD,
) -> str:
    """Register a user via the API and return the emailed verification secret."""
    with capture(execute=True):
        response = api_client.post(
            REGISTER_URL, {"email": email, "password": password}, format="json"
        )
    assert response.status_code == 201, response.data
    return str(InMemoryEmailBackend.outbox[-1].context["token"])


def test_register_creates_unverified_user(api_client: APIClient) -> None:
    response = api_client.post(REGISTER_URL, {"email": EMAIL, "password": PASSWORD}, format="json")
    assert response.status_code == 201, response.data
    assert response.data["email"] == EMAIL
    user = get_user_model().objects.get(email=EMAIL)
    assert user.check_password(PASSWORD)
    assert user.email_verified is False


def test_register_sends_verification_email_on_commit(
    api_client: APIClient,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        response = api_client.post(
            REGISTER_URL, {"email": EMAIL, "password": PASSWORD}, format="json"
        )
    assert response.status_code == 201, response.data
    assert len(InMemoryEmailBackend.outbox) == 1
    sent = InMemoryEmailBackend.outbox[0]
    assert sent.template == "verify_email"
    assert sent.to == EMAIL
    assert sent.context["user"].email == EMAIL
    # The emailed link carries the raw secret the verify endpoint accepts.
    assert sent.context["token"] in sent.context["link"]


def test_register_email_waits_for_commit(
    api_client: APIClient,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """A7: the email is deferred to transaction.on_commit, not sent inline."""
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        response = api_client.post(
            REGISTER_URL, {"email": EMAIL, "password": PASSWORD}, format="json"
        )
    assert response.status_code == 201, response.data
    # Nothing sent while the registration transaction is still open ...
    assert InMemoryEmailBackend.outbox == []
    # ... because the send sits in the commit callback queue.
    assert callbacks


def test_register_honeypot_accepts_and_creates_nothing(
    api_client: APIClient, settings: Settings
) -> None:
    """A filled honeypot field is a script: pretend to accept, create no user, send no mail."""
    from structlog.testing import capture_logs

    payload = {"email": EMAIL, "password": PASSWORD, "website": "http://spam.example"}
    with capture_logs() as logs:
        response = api_client.post(REGISTER_URL, payload, format="json")
    assert response.status_code == 202, response.data
    assert not get_user_model().objects.filter(email=EMAIL).exists()
    assert InMemoryEmailBackend.outbox == []
    events = [entry["event"] for entry in logs if entry["event"].startswith("accounts.")]
    assert events == ["accounts.register.honeypot"]
    assert EMAIL not in str(logs)

    settings.KARNI_ACCOUNTS_HONEYPOT_FIELD = ""  # off: the field is just ignored
    response = api_client.post(REGISTER_URL, payload, format="json")
    assert response.status_code == 201, response.data


def test_register_duplicate_email_returns_400(api_client: APIClient) -> None:
    """A9: register necessarily reveals existence via the unique-email 400."""
    get_user_model().objects.create_user(email=EMAIL, password=PASSWORD)
    response = api_client.post(REGISTER_URL, {"email": EMAIL, "password": PASSWORD}, format="json")
    assert response.status_code == 400


def test_verify_email_marks_user_verified(
    api_client: APIClient,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    token = _register(api_client, django_capture_on_commit_callbacks)
    response = api_client.post(VERIFY_URL, {"token": token}, format="json")
    assert response.status_code == 200, response.data
    user = get_user_model().objects.get(email=EMAIL)
    assert user.email_verified is True


def test_verify_email_replay_rejected(
    api_client: APIClient,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    token = _register(api_client, django_capture_on_commit_callbacks)
    assert api_client.post(VERIFY_URL, {"token": token}, format="json").status_code == 200
    replay = api_client.post(VERIFY_URL, {"token": token}, format="json")
    assert replay.status_code == 400
    # The user stays verified; the replay just fails.
    assert get_user_model().objects.get(email=EMAIL).email_verified is True


def test_verify_email_unknown_token_rejected(api_client: APIClient) -> None:
    response = api_client.post(VERIFY_URL, {"token": "not-a-real-token"}, format="json")
    assert response.status_code == 400


def test_resend_requires_authentication(api_client: APIClient) -> None:
    """A9: resend is auth-required (and may therefore respond honestly)."""
    response = api_client.post(RESEND_URL, {}, format="json")
    assert response.status_code in (401, 403)


def test_resend_issues_fresh_link_and_invalidates_old(
    api_client: APIClient,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    old_token = _register(api_client, django_capture_on_commit_callbacks)
    user = get_user_model().objects.get(email=EMAIL)

    api_client.force_authenticate(user)
    with django_capture_on_commit_callbacks(execute=True):
        response = api_client.post(RESEND_URL, {}, format="json")
    assert 200 <= response.status_code < 300, response.data

    assert len(InMemoryEmailBackend.outbox) == 2
    resent = InMemoryEmailBackend.outbox[-1]
    assert resent.template == "verify_email"
    assert resent.to == EMAIL
    new_token = str(resent.context["token"])
    assert new_token != old_token

    # Single active token per purpose: the old link is dead, the new one works.
    assert api_client.post(VERIFY_URL, {"token": old_token}, format="json").status_code == 400
    assert api_client.post(VERIFY_URL, {"token": new_token}, format="json").status_code == 200
    user.refresh_from_db()
    assert user.email_verified is True


# KARNI_ACCOUNTS_REGISTRATION


def _urlconf_for_current_settings() -> ModuleType:
    """A URLconf built now: karni.accounts.urls builds its list once, at import."""
    module = ModuleType("registration_urls")
    module.__dict__["urlpatterns"] = [
        path("api/auth/", include(build_urlpatterns())),
        path("api/", include("karni.api.urls")),
    ]
    return module


def _route_names() -> set[str]:
    return {p.name for p in build_urlpatterns() if isinstance(p, URLPattern) and p.name}


def test_registration_is_open_by_default(api_client: APIClient, settings: Settings) -> None:
    assert settings.KARNI_ACCOUNTS_REGISTRATION is True
    assert "karni-accounts-register" in _route_names()
    assert "/api/auth/register/" in generate_schema()["paths"]


def test_closed_registration_is_a_404_and_absent_from_the_schema(
    api_client: APIClient, settings: Settings
) -> None:
    settings.KARNI_ACCOUNTS_REGISTRATION = False
    assert "karni-accounts-register" not in _route_names()
    assert "karni-accounts-login" in _route_names()
    settings.ROOT_URLCONF = _urlconf_for_current_settings()
    response = api_client.post(REGISTER_URL, {"email": EMAIL, "password": PASSWORD}, format="json")
    assert response.status_code == 404
    assert not get_user_model().objects.filter(email=EMAIL).exists()
    paths = generate_schema()["paths"]
    assert "/api/auth/register/" not in paths
    assert "/api/auth/login/" in paths
