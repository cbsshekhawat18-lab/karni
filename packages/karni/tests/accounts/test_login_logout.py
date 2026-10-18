"""Login, logout and refresh flows in both auth modes.

Covers (contract §API + amendments A1/A3/A15): the JWT login payload (token
pair plus the ``MeSerializer`` user with its ``roles`` list),
indistinguishable 401s for wrong-password / unknown-address /
inactive-account failures, logout blacklisting the posted refresh token,
refresh rotation blacklisting the replaced token, and the session-mode
branches — login opens a Django session, logout flushes it, ``refresh/``
answers 405 — all switched per request by ``KARNI_AUTH_MODE`` (amendment A3),
so overriding the setting flips modes without touching the URLconf.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.core.cache import cache
from pytest_django import Settings
from rest_framework.test import APIClient

from karni.accounts.models import AbstractKarniUser, User
from karni.accounts.permissions import assign_role

pytestmark = pytest.mark.django_db

LOGIN_URL = "/api/auth/login/"
LOGOUT_URL = "/api/auth/logout/"
REFRESH_URL = "/api/auth/refresh/"
ME_URL = "/api/auth/me/"

EMAIL = "login-user@example.com"
PASSWORD = "log-me-in-p4ss-77"


@pytest.fixture(autouse=True)
def _fresh_throttle_state() -> Iterator[None]:
    """Scoped auth throttles count hits in the default cache; isolate tests."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


def _make_user(email: str = EMAIL, password: str = PASSWORD) -> AbstractKarniUser:
    return User.objects.create_user(email=email, password=password)


def _login(api_client: APIClient, email: str = EMAIL, password: str = PASSWORD) -> dict[str, Any]:
    """Log in and return the response payload (mode-agnostic)."""
    response = api_client.post(LOGIN_URL, {"email": email, "password": password}, format="json")
    assert response.status_code == 200, response.data
    return dict(response.data)


# JWT mode: login


def test_jwt_login_returns_token_pair_and_user(api_client: APIClient) -> None:
    user = _make_user()
    assign_role(user, "editor")
    data = _login(api_client)
    assert data["access"]
    assert data["refresh"]
    payload = data["user"]
    assert payload["email"] == EMAIL
    # Amendment A15: the embedded MeSerializer payload carries the role names.
    assert payload["roles"] == ["editor"]
    assert "password" not in payload


def test_jwt_access_token_authenticates_requests(api_client: APIClient) -> None:
    _make_user()
    data = _login(api_client)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {data['access']}")
    me = api_client.get(ME_URL)
    assert me.status_code == 200, me.data
    assert me.data["email"] == EMAIL


def test_login_wrong_password_rejected(api_client: APIClient) -> None:
    _make_user()
    response = api_client.post(
        LOGIN_URL, {"email": EMAIL, "password": "not-the-p4ssword"}, format="json"
    )
    assert response.status_code == 401


def test_login_unknown_email_indistinguishable_from_wrong_password(
    api_client: APIClient,
) -> None:
    """Failure responses never reveal whether the address has an account."""
    _make_user()
    wrong_password = api_client.post(
        LOGIN_URL, {"email": EMAIL, "password": "not-the-p4ssword"}, format="json"
    )
    unknown = api_client.post(
        LOGIN_URL, {"email": "ghost@example.com", "password": PASSWORD}, format="json"
    )
    assert wrong_password.status_code == unknown.status_code == 401
    assert wrong_password.data == unknown.data


def test_login_outcomes_are_logged_without_addresses(api_client: APIClient) -> None:
    """Security events carry a user id or an address fingerprint, never the address."""
    from structlog.testing import capture_logs

    user = _make_user()
    with capture_logs() as logs:
        api_client.post(LOGIN_URL, {"email": EMAIL, "password": "not-the-p4ssword"}, format="json")
        _login(api_client)
    # django-structlog's request_started/finished ride along; keep the account events.
    events = {entry["event"]: entry for entry in logs if entry["event"].startswith("accounts.")}
    assert set(events) == {"accounts.login.failed", "accounts.login.ok"}
    assert events["accounts.login.ok"]["user_id"] == str(user.pk)
    assert len(events["accounts.login.failed"]["email"]) == 16
    assert EMAIL not in str(logs)


def test_login_inactive_user_rejected(api_client: APIClient) -> None:
    user = _make_user()
    user.is_active = False
    user.save(update_fields=["is_active", "updated_at"])
    response = api_client.post(LOGIN_URL, {"email": EMAIL, "password": PASSWORD}, format="json")
    assert response.status_code == 401


# JWT mode: logout


def test_jwt_logout_blacklists_posted_refresh_token(api_client: APIClient) -> None:
    _make_user()
    data = _login(api_client)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {data['access']}")
    logout = api_client.post(LOGOUT_URL, {"refresh": data["refresh"]}, format="json")
    assert logout.status_code == 204, logout.data

    api_client.credentials()
    stale = api_client.post(REFRESH_URL, {"refresh": data["refresh"]}, format="json")
    assert stale.status_code == 401


def test_jwt_logout_requires_refresh_token(api_client: APIClient) -> None:
    user = _make_user()
    api_client.force_authenticate(user)
    response = api_client.post(LOGOUT_URL, {}, format="json")
    assert response.status_code == 400
    assert "refresh" in response.data


def test_jwt_logout_rejects_malformed_refresh_token(api_client: APIClient) -> None:
    user = _make_user()
    api_client.force_authenticate(user)
    response = api_client.post(LOGOUT_URL, {"refresh": "not-a-jwt"}, format="json")
    assert response.status_code == 400


def test_logout_requires_authentication(api_client: APIClient) -> None:
    response = api_client.post(LOGOUT_URL, {}, format="json")
    assert response.status_code in (401, 403)


# JWT mode: refresh rotation


def test_jwt_refresh_rotates_and_blacklists_previous_token(api_client: APIClient) -> None:
    """Karni's SIMPLE_JWT defaults rotate refresh tokens and kill the old one."""
    _make_user()
    original = str(_login(api_client)["refresh"])

    rotated = api_client.post(REFRESH_URL, {"refresh": original}, format="json")
    assert rotated.status_code == 200, rotated.data
    assert rotated.data["access"]
    new_refresh = str(rotated.data["refresh"])
    assert new_refresh != original

    # BLACKLIST_AFTER_ROTATION: the replaced token is dead...
    replay = api_client.post(REFRESH_URL, {"refresh": original}, format="json")
    assert replay.status_code == 401
    # ...while the rotated one keeps working.
    current = api_client.post(REFRESH_URL, {"refresh": new_refresh}, format="json")
    assert current.status_code == 200, current.data


# Session mode


def test_session_login_opens_session_without_tokens(settings: Settings) -> None:
    settings.KARNI_AUTH_MODE = "session"
    client = APIClient()
    _make_user()
    data = _login(client)
    assert "access" not in data
    assert "refresh" not in data
    assert data["user"]["email"] == EMAIL

    # The session cookie alone is the credential from here on.
    me = client.get(ME_URL)
    assert me.status_code == 200, me.data
    assert me.data["email"] == EMAIL


def test_session_logout_flushes_session(settings: Settings) -> None:
    settings.KARNI_AUTH_MODE = "session"
    client = APIClient()
    _make_user()
    _login(client)
    logout = client.post(LOGOUT_URL, {}, format="json")
    assert logout.status_code == 204, logout.data

    me = client.get(ME_URL)
    assert me.status_code in (401, 403)


def test_session_refresh_returns_405(settings: Settings) -> None:
    """A3: the refresh URL exists in session mode but the view answers 405."""
    settings.KARNI_AUTH_MODE = "session"
    client = APIClient()
    _make_user()
    _login(client)
    response = client.post(REFRESH_URL, {"refresh": "anything"}, format="json")
    assert response.status_code == 405
    assert "session" in str(response.data["detail"]).lower()


def test_auth_mode_is_read_at_request_time(settings: Settings) -> None:
    """A3: flipping KARNI_AUTH_MODE switches behaviour per request, no reload."""
    _make_user()
    jwt_data = _login(APIClient())
    assert "access" in jwt_data
    assert "refresh" in jwt_data

    settings.KARNI_AUTH_MODE = "session"
    session_data = _login(APIClient())
    assert "access" not in session_data
    assert "refresh" not in session_data
