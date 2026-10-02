"""Email-change flow tests.

Covers: the request (auth + current password, confirmation emailed to the NEW
address), uniqueness enforced at request time AND re-checked at confirm time,
replay protection, and the amendment A7/A13 guarantee that a uniqueness race
between request and confirm yields a 400 — never a 500.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from pytest_django import DjangoCaptureOnCommitCallbacks, Settings
from rest_framework.test import APIClient

from karni.accounts.emails import InMemoryEmailBackend
from karni.accounts.models import User

pytestmark = pytest.mark.django_db

CHANGE_URL = "/api/auth/email/change/"
CONFIRM_URL = "/api/auth/email/change/confirm/"

EMAIL = "primary@example.com"
NEW_EMAIL = "fresh@example.com"
OTHER_EMAIL = "taken@example.com"
PASSWORD = "sturdy-p4ssword-33"


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


def _request_change(
    api_client: APIClient,
    user: User,
    capture: DjangoCaptureOnCommitCallbacks,
    new_email: str = NEW_EMAIL,
) -> str:
    """Request an email change as ``user`` and return the emailed secret."""
    api_client.force_authenticate(user)
    with capture(execute=True):
        response = api_client.post(
            CHANGE_URL, {"new_email": new_email, "current_password": PASSWORD}, format="json"
        )
    assert 200 <= response.status_code < 300, response.data
    return str(InMemoryEmailBackend.outbox[-1].context["token"])


def test_request_requires_authentication(api_client: APIClient) -> None:
    response = api_client.post(
        CHANGE_URL, {"new_email": NEW_EMAIL, "current_password": PASSWORD}, format="json"
    )
    assert response.status_code in (401, 403)


def test_request_sends_confirmation_to_new_address(
    api_client: APIClient,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    user = _make_user()
    api_client.force_authenticate(user)
    with django_capture_on_commit_callbacks(execute=True):
        response = api_client.post(
            CHANGE_URL, {"new_email": NEW_EMAIL, "current_password": PASSWORD}, format="json"
        )
    assert 200 <= response.status_code < 300, response.data
    assert len(InMemoryEmailBackend.outbox) == 1
    sent = InMemoryEmailBackend.outbox[0]
    assert sent.template == "change_email"
    # The link goes to the NEW mailbox — following it proves ownership.
    assert sent.to == NEW_EMAIL
    assert sent.context["new_email"] == NEW_EMAIL
    assert sent.context["token"] in sent.context["link"]
    # Nothing changes until the link is confirmed.
    user.refresh_from_db()
    assert user.email == EMAIL


def test_request_requires_current_password(api_client: APIClient) -> None:
    user = _make_user()
    api_client.force_authenticate(user)
    response = api_client.post(
        CHANGE_URL,
        {"new_email": NEW_EMAIL, "current_password": "not-the-p4ssword"},
        format="json",
    )
    assert response.status_code == 400
    assert InMemoryEmailBackend.outbox == []


def test_request_rejects_taken_email(api_client: APIClient) -> None:
    """A9: uniqueness at request time is a 400 (accepted enumeration surface)."""
    user = _make_user()
    _make_user(email=OTHER_EMAIL)
    api_client.force_authenticate(user)
    response = api_client.post(
        CHANGE_URL, {"new_email": OTHER_EMAIL, "current_password": PASSWORD}, format="json"
    )
    assert response.status_code == 400
    assert InMemoryEmailBackend.outbox == []
    user.refresh_from_db()
    assert user.email == EMAIL


def test_confirm_changes_email_and_marks_verified(
    api_client: APIClient,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    user = _make_user()
    token = _request_change(api_client, user, django_capture_on_commit_callbacks)
    # The link lands on an unauthenticated frontend page — confirm anonymously.
    anon = APIClient()
    response = anon.post(CONFIRM_URL, {"token": token}, format="json")
    assert 200 <= response.status_code < 300, response.data
    user.refresh_from_db()
    assert user.email == NEW_EMAIL
    # Following the emailed link proves ownership of the new address.
    assert user.email_verified is True


def test_confirm_replay_rejected(
    api_client: APIClient,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    user = _make_user()
    token = _request_change(api_client, user, django_capture_on_commit_callbacks)
    first = api_client.post(CONFIRM_URL, {"token": token}, format="json")
    assert 200 <= first.status_code < 300, first.data
    replay = api_client.post(CONFIRM_URL, {"token": token}, format="json")
    assert replay.status_code == 400
    user.refresh_from_db()
    assert user.email == NEW_EMAIL


def test_confirm_unknown_token_rejected(api_client: APIClient) -> None:
    response = api_client.post(CONFIRM_URL, {"token": "not-a-real-token"}, format="json")
    assert response.status_code == 400


def test_confirm_uniqueness_race_returns_400_not_500(
    api_client: APIClient,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """A7/A13: an address claimed between request and confirm → clean 400."""
    user = _make_user()
    token = _request_change(api_client, user, django_capture_on_commit_callbacks)
    # Another account grabs the target address before the link is clicked.
    _make_user(email=NEW_EMAIL, password="another-p4ssword-58")

    response = api_client.post(CONFIRM_URL, {"token": token}, format="json")
    assert response.status_code == 400
    user.refresh_from_db()
    assert user.email == EMAIL
    assert user.email_verified is False
