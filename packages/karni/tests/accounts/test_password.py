"""Password change and reset flow tests.

Covers: the enumeration-silent reset request, the full reset flow, token
expiry and reuse, password validators (with the weak-password attempt leaving
the token unused — the A7 atomicity guarantee), change requiring the current
password, and the amendment A1 guarantees: all outstanding refresh tokens are
blacklisted after a reset AND after a password change, while a session-mode
user's own session survives their password change.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from pytest_django import DjangoCaptureOnCommitCallbacks, Settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)

from karni.accounts.emails import InMemoryEmailBackend
from karni.accounts.models import OneTimeToken, User

pytestmark = pytest.mark.django_db

LOGIN_URL = "/api/auth/login/"
REFRESH_URL = "/api/auth/refresh/"
ME_URL = "/api/auth/me/"
CHANGE_URL = "/api/auth/password/change/"
RESET_URL = "/api/auth/password/reset/"
RESET_CONFIRM_URL = "/api/auth/password/reset/confirm/"

EMAIL = "resetta@example.com"
PASSWORD = "original-p4ssword-77"
NEW_PASSWORD = "brand-new-p4ss-42"


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


def _make_user(email: str = EMAIL, password: str = PASSWORD) -> User:
    return get_user_model().objects.create_user(email=email, password=password)


def _request_reset_token(
    api_client: APIClient,
    capture: DjangoCaptureOnCommitCallbacks,
    email: str = EMAIL,
) -> str:
    """Request a password reset and return the emailed secret."""
    with capture(execute=True):
        response = api_client.post(RESET_URL, {"email": email}, format="json")
    assert response.status_code in (200, 202), response.data
    return str(InMemoryEmailBackend.outbox[-1].context["token"])


def _login(api_client: APIClient, email: str = EMAIL, password: str = PASSWORD) -> str:
    """Log in (jwt mode) and return the refresh token."""
    response = api_client.post(LOGIN_URL, {"email": email, "password": password}, format="json")
    assert response.status_code == 200, response.data
    return str(response.data["refresh"])


# --- Reset request ---------------------------------------------------------


def test_reset_request_sends_email(
    api_client: APIClient,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    _make_user()
    with django_capture_on_commit_callbacks(execute=True):
        response = api_client.post(RESET_URL, {"email": EMAIL}, format="json")
    assert response.status_code in (200, 202), response.data
    assert len(InMemoryEmailBackend.outbox) == 1
    sent = InMemoryEmailBackend.outbox[0]
    assert sent.template == "reset_password"
    assert sent.to == EMAIL
    assert sent.context["token"] in sent.context["link"]


def test_reset_request_is_enumeration_silent(
    api_client: APIClient,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """Known and unknown addresses get identical responses; no mail leaks."""
    _make_user()
    with django_capture_on_commit_callbacks(execute=True):
        known = api_client.post(RESET_URL, {"email": EMAIL}, format="json")
    InMemoryEmailBackend.clear()
    with django_capture_on_commit_callbacks(execute=True):
        unknown = api_client.post(RESET_URL, {"email": "ghost@example.com"}, format="json")
    assert unknown.status_code == known.status_code
    assert InMemoryEmailBackend.outbox == []


# --- Reset confirm ---------------------------------------------------------


def test_reset_confirm_sets_new_password(
    api_client: APIClient,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    user = _make_user()
    token = _request_reset_token(api_client, django_capture_on_commit_callbacks)
    response = api_client.post(
        RESET_CONFIRM_URL, {"token": token, "new_password": NEW_PASSWORD}, format="json"
    )
    assert 200 <= response.status_code < 300, response.data
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD)
    assert not user.check_password(PASSWORD)


def test_reset_token_reuse_rejected(
    api_client: APIClient,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    user = _make_user()
    token = _request_reset_token(api_client, django_capture_on_commit_callbacks)
    first = api_client.post(
        RESET_CONFIRM_URL, {"token": token, "new_password": NEW_PASSWORD}, format="json"
    )
    assert 200 <= first.status_code < 300, first.data
    replay = api_client.post(
        RESET_CONFIRM_URL, {"token": token, "new_password": "sneaky-p4ss-13"}, format="json"
    )
    assert replay.status_code == 400
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD)


def test_reset_token_expiry_rejected(
    api_client: APIClient,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    user = _make_user()
    token = _request_reset_token(api_client, django_capture_on_commit_callbacks)
    OneTimeToken.objects.filter(user=user, purpose="reset_password").update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    response = api_client.post(
        RESET_CONFIRM_URL, {"token": token, "new_password": NEW_PASSWORD}, format="json"
    )
    assert response.status_code == 400
    user.refresh_from_db()
    assert user.check_password(PASSWORD)


def test_reset_confirm_enforces_password_validators(
    api_client: APIClient,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    user = _make_user()
    token = _request_reset_token(api_client, django_capture_on_commit_callbacks)
    weak = api_client.post(
        RESET_CONFIRM_URL, {"token": token, "new_password": "short"}, format="json"
    )
    assert weak.status_code == 400
    user.refresh_from_db()
    assert user.check_password(PASSWORD)
    # A7 atomicity: the rejected attempt rolled back, so the token is still
    # unused and the emailed link can be retried with a stronger password.
    retry = api_client.post(
        RESET_CONFIRM_URL, {"token": token, "new_password": NEW_PASSWORD}, format="json"
    )
    assert 200 <= retry.status_code < 300, retry.data
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD)


def test_reset_confirm_blacklists_outstanding_refresh_tokens(
    api_client: APIClient,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """A1: a password reset kills every outstanding refresh token."""
    user = _make_user()
    refresh = _login(api_client)
    token = _request_reset_token(api_client, django_capture_on_commit_callbacks)
    confirm = api_client.post(
        RESET_CONFIRM_URL, {"token": token, "new_password": NEW_PASSWORD}, format="json"
    )
    assert 200 <= confirm.status_code < 300, confirm.data

    outstanding = OutstandingToken.objects.filter(user=user)
    assert outstanding.exists()
    for issued in outstanding:
        assert BlacklistedToken.objects.filter(token=issued).exists()

    stale = api_client.post(REFRESH_URL, {"refresh": refresh}, format="json")
    assert stale.status_code == 401


# --- Password change -------------------------------------------------------


def test_change_password_requires_authentication(api_client: APIClient) -> None:
    response = api_client.post(
        CHANGE_URL, {"current_password": PASSWORD, "new_password": NEW_PASSWORD}, format="json"
    )
    assert response.status_code in (401, 403)


def test_change_password_requires_current_password(api_client: APIClient) -> None:
    user = _make_user()
    api_client.force_authenticate(user)
    wrong = api_client.post(
        CHANGE_URL,
        {"current_password": "not-the-p4ssword", "new_password": NEW_PASSWORD},
        format="json",
    )
    assert wrong.status_code == 400
    user.refresh_from_db()
    assert user.check_password(PASSWORD)

    right = api_client.post(
        CHANGE_URL, {"current_password": PASSWORD, "new_password": NEW_PASSWORD}, format="json"
    )
    assert 200 <= right.status_code < 300, right.data
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD)


def test_change_password_enforces_password_validators(api_client: APIClient) -> None:
    user = _make_user()
    api_client.force_authenticate(user)
    response = api_client.post(
        CHANGE_URL, {"current_password": PASSWORD, "new_password": "short"}, format="json"
    )
    assert response.status_code == 400
    user.refresh_from_db()
    assert user.check_password(PASSWORD)


def test_change_password_blacklists_outstanding_refresh_tokens(api_client: APIClient) -> None:
    """A1: a password change kills every outstanding refresh token."""
    user = _make_user()
    refresh = _login(api_client)

    api_client.force_authenticate(user)
    change = api_client.post(
        CHANGE_URL, {"current_password": PASSWORD, "new_password": NEW_PASSWORD}, format="json"
    )
    assert 200 <= change.status_code < 300, change.data
    api_client.force_authenticate(None)

    outstanding = OutstandingToken.objects.filter(user=user)
    assert outstanding.exists()
    for issued in outstanding:
        assert BlacklistedToken.objects.filter(token=issued).exists()

    stale = api_client.post(REFRESH_URL, {"refresh": refresh}, format="json")
    assert stale.status_code == 401


def test_session_survives_own_password_change(settings: Settings) -> None:
    """A1: session mode calls update_session_auth_hash — the changer stays in."""
    settings.KARNI_AUTH_MODE = "session"
    session_client = APIClient()
    _make_user()

    login = session_client.post(LOGIN_URL, {"email": EMAIL, "password": PASSWORD}, format="json")
    assert login.status_code == 200, login.data

    change = session_client.post(
        CHANGE_URL, {"current_password": PASSWORD, "new_password": NEW_PASSWORD}, format="json"
    )
    assert 200 <= change.status_code < 300, change.data

    me = session_client.get(ME_URL)
    assert me.status_code == 200, me.data
    assert me.data["email"] == EMAIL
