"""JWT auth: tokens for the target carry the session; stop hands back the actor's."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone
from karni.audit.models import ChangeLog
from rest_framework.test import APIClient

from karni_impersonation.models import ImpersonationSession
from karni_impersonation.tokens import CLAIM, session_id_from_token
from tests.testapp.models import Note

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _jwt(settings: Any) -> None:
    settings.KARNI_AUTH_MODE = "jwt"


def test_start_act_block_and_stop(support: Any, customer: Any) -> None:
    client = APIClient()
    client.force_authenticate(support)
    started = client.post(
        "/api/impersonation-sessions/start/",
        {"user": "customer@example.com", "reason": "ticket"},
        format="json",
    )
    assert started.status_code == 201, started.content
    body = started.json()
    assert (
        body["session"]["target"]["email"] == "customer@example.com" and body["session"]["active"]
    )
    assert session_id_from_token(body["access"]) == body["session"]["id"]
    session = ImpersonationSession.objects.get()

    acting = APIClient()
    acting.credentials(HTTP_AUTHORIZATION=f"Bearer {body['access']}")
    assert acting.get("/api/auth/me/").json()["email"] == "customer@example.com"
    current = acting.get("/api/impersonation-sessions/current/").json()["session"]
    assert current["id"] == str(session.pk) and current["actor"]["email"] == "support@example.com"
    created = acting.post("/api/notes/", {"text": "as customer"}, format="json")
    assert created.status_code == 201
    entry = ChangeLog.objects.for_object(Note.objects.get(text="as customer")).get()
    assert entry.actor == customer and entry.batch.actor == support
    deleted = acting.delete(f"/api/notes/{Note.objects.get().pk}/")
    assert deleted.status_code == 403 and "IMP006" in str(deleted.json())
    assert acting.post("/api/auth/password/change/", {}, format="json").status_code == 403

    stopped = acting.post(
        "/api/impersonation-sessions/stop/", {"refresh": body["refresh"]}, format="json"
    )
    assert stopped.status_code == 200, stopped.content
    assert stopped.json()["session"]["end_reason"] == "stopped" and "access" in stopped.json()
    assert session_id_from_token(stopped.json()["access"]) is None
    back = APIClient()
    back.credentials(HTTP_AUTHORIZATION=f"Bearer {stopped.json()['access']}")
    assert back.get("/api/auth/me/").json()["email"] == "support@example.com"
    # The old impersonation token is dead once the session ended.
    assert acting.get("/api/auth/me/").status_code == 401
    assert client.get("/api/impersonation-sessions/current/").json() == {"session": None}


def test_the_tokens_never_outlive_the_session(support: Any, customer: Any, settings: Any) -> None:
    settings.KARNI_IMPERSONATION_MAX_MINUTES = 2
    client = APIClient()
    client.force_authenticate(support)
    body = client.post(
        "/api/impersonation-sessions/start/",
        {"user": str(customer.pk), "reason": "ticket"},
        format="json",
    ).json()
    from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

    now = timezone.now().timestamp()
    assert AccessToken(body["access"])["exp"] - now <= 2 * 60 + 5
    assert RefreshToken(body["refresh"])["exp"] - now <= 2 * 60 + 5
    assert RefreshToken(body["refresh"])[CLAIM] == body["session"]["id"]


def test_refusals_through_the_api(support: Any, customer: Any, finance: Any) -> None:
    client = APIClient()
    client.force_authenticate(customer)  # no impersonate grant
    assert (
        client.post(
            "/api/impersonation-sessions/start/",
            {"user": str(support.pk), "reason": "x"},
            format="json",
        ).status_code
        == 403
    )
    client.force_authenticate(support)
    escalation = client.post(
        "/api/impersonation-sessions/start/",
        {"user": str(finance.pk), "reason": "x"},
        format="json",
    )
    assert escalation.status_code == 403 and "IMP002" in str(escalation.json())
    no_reason = client.post(
        "/api/impersonation-sessions/start/",
        {"user": str(customer.pk), "reason": ""},
        format="json",
    )
    assert no_reason.status_code == 400 and "IMP003" in str(no_reason.json())
    assert (
        client.post(
            "/api/impersonation-sessions/start/",
            {"user": "ghost@example.com", "reason": "x"},
            format="json",
        ).status_code
        == 404
    )
    assert client.post("/api/impersonation-sessions/stop/", {}, format="json").status_code == 400
    # The log is read-only: the write gate refuses (a superuser reaches the 405 handlers).
    assert client.post("/api/impersonation-sessions/", {}, format="json").status_code == 403
    client.post(
        "/api/impersonation-sessions/start/",
        {"user": str(customer.pk), "reason": "x"},
        format="json",
    )
    listed = client.get("/api/impersonation-sessions/").json()
    assert listed["count"] == 1 and listed["results"][0]["actor"]["email"] == "support@example.com"
    session_id = listed["results"][0]["id"]
    assert client.delete(f"/api/impersonation-sessions/{session_id}/").status_code == 403
    ImpersonationSession.objects.filter(pk=session_id).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
