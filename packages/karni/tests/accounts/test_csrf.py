"""CSRF bootstrap tests (amendments A4 + A13).

``login/`` and the dedicated ``csrf/`` endpoint both carry
``ensure_csrf_cookie``, so an SPA always holds a CSRF cookie before its first
credentialed unsafe request. DRF views are ``csrf_exempt`` at the middleware
level — the anonymous login POST itself is deliberately not checked — and in
session mode DRF's ``SessionAuthentication`` enforces the cookie/header pair
on every unsafe request of an authenticated session instead. JWT requests
carry no session and are never CSRF-checked.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from django.core.cache import cache
from pytest_django import Settings
from rest_framework.test import APIClient

from karni.accounts.models import User

pytestmark = pytest.mark.django_db

CSRF_URL = "/api/auth/csrf/"
LOGIN_URL = "/api/auth/login/"
LOGOUT_URL = "/api/auth/logout/"
ME_URL = "/api/auth/me/"

EMAIL = "csrf-user@example.com"
PASSWORD = "csrf-p4ssword-55"


@pytest.fixture(autouse=True)
def _fresh_throttle_state() -> Iterator[None]:
    """Scoped auth throttles count hits in the default cache; isolate tests."""
    cache.clear()
    yield
    cache.clear()


def _make_user() -> None:
    User.objects.create_user(email=EMAIL, password=PASSWORD)


def _csrf_cookie(client: APIClient) -> str:
    """The CSRF secret currently stored in the client's cookie jar."""
    return str(client.cookies["csrftoken"].value)


# --- Cookie bootstrap (A4 / A13: cookie set on csrf/ and login/) --------------


def test_csrf_endpoint_sets_cookie_and_returns_204() -> None:
    client = APIClient()
    response = client.get(CSRF_URL)
    assert response.status_code == 204
    assert "csrftoken" in response.cookies
    assert response.cookies["csrftoken"].value


def test_login_sets_csrf_cookie() -> None:
    """ensure_csrf_cookie on login: a cookie arrives even in JWT mode."""
    _make_user()
    client = APIClient()
    response = client.post(LOGIN_URL, {"email": EMAIL, "password": PASSWORD}, format="json")
    assert response.status_code == 200, response.data
    assert "csrftoken" in response.cookies
    assert response.cookies["csrftoken"].value


def test_session_login_rotates_and_resends_csrf_cookie(settings: Settings) -> None:
    """Django rotates the CSRF secret on login; the fresh cookie ships with it."""
    settings.KARNI_AUTH_MODE = "session"
    _make_user()
    client = APIClient(enforce_csrf_checks=True)

    bootstrap = client.get(CSRF_URL)
    pre_login = str(bootstrap.cookies["csrftoken"].value)

    login = client.post(LOGIN_URL, {"email": EMAIL, "password": PASSWORD}, format="json")
    assert login.status_code == 200, login.data
    assert "csrftoken" in login.cookies
    assert login.cookies["csrftoken"].value != pre_login


# --- Session-mode enforcement --------------------------------------------------


def test_session_unsafe_request_requires_csrf_header(settings: Settings) -> None:
    """SessionAuthentication rejects an authenticated POST without the header."""
    settings.KARNI_AUTH_MODE = "session"
    _make_user()
    client = APIClient(enforce_csrf_checks=True)

    login = client.post(LOGIN_URL, {"email": EMAIL, "password": PASSWORD}, format="json")
    assert login.status_code == 200, login.data

    missing = client.post(LOGOUT_URL, {}, format="json")
    assert missing.status_code == 403
    assert "csrf" in str(missing.data["detail"]).lower()

    with_header = client.post(LOGOUT_URL, {}, format="json", HTTP_X_CSRFTOKEN=_csrf_cookie(client))
    assert with_header.status_code == 204, with_header.data

    me = client.get(ME_URL)
    assert me.status_code in (401, 403)


def test_spa_csrf_bootstrap_flow(settings: Settings) -> None:
    """A4 end to end: GET csrf/ → cookie; login; cookie authorises unsafe calls."""
    settings.KARNI_AUTH_MODE = "session"
    _make_user()
    client = APIClient(enforce_csrf_checks=True)

    bootstrap = client.get(CSRF_URL)
    assert bootstrap.status_code == 204
    assert _csrf_cookie(client)

    login = client.post(LOGIN_URL, {"email": EMAIL, "password": PASSWORD}, format="json")
    assert login.status_code == 200, login.data

    # The post-login (rotated) cookie value is what the SPA echoes back.
    logout = client.post(LOGOUT_URL, {}, format="json", HTTP_X_CSRFTOKEN=_csrf_cookie(client))
    assert logout.status_code == 204, logout.data


# --- JWT mode is cookie-free ----------------------------------------------------


def test_jwt_requests_are_never_csrf_checked() -> None:
    """Bearer-authenticated unsafe requests need no CSRF header (no session)."""
    _make_user()
    client = APIClient(enforce_csrf_checks=True)

    login = client.post(LOGIN_URL, {"email": EMAIL, "password": PASSWORD}, format="json")
    assert login.status_code == 200, login.data

    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    logout = client.post(LOGOUT_URL, {"refresh": login.data["refresh"]}, format="json")
    assert logout.status_code == 204, logout.data
