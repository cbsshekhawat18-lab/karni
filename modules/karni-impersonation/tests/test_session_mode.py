"""Session auth: the admin start page, the banner, the swapped identity, the blocks, the exit."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from karni.audit.models import ChangeLog

from karni_impersonation.models import ImpersonationSession
from tests.conftest import make_user
from tests.testapp.models import Note

pytestmark = pytest.mark.django_db

START = reverse("admin:karni_impersonation_impersonationsession_impersonate_user")
STOP = reverse("karni-impersonation-stop")


def begin(support: Any, customer: Any) -> Client:
    client = Client()
    client.force_login(support)
    response = client.post(START, {"user": customer.email, "reason": "ticket #7"})
    assert response.status_code == 302 and response["Location"] == "/"
    return client


def test_the_start_page_refuses_without_a_reason_and_without_the_grant(
    support: Any, customer: Any
) -> None:
    client = Client()
    client.force_login(support)
    page = client.get(START)
    assert page.status_code == 200 and 'name="reason"' in page.content.decode()
    refused = client.post(START, {"user": customer.email, "reason": ""}, follow=True)
    assert "IMP003" in refused.content.decode() and not ImpersonationSession.objects.exists()
    nobody = make_user("nobody@example.com", staff=True)
    client.force_login(nobody)
    assert client.get(START).status_code == 403  # no Django view permission on the log


def test_the_whole_session(support: Any, customer: Any) -> None:
    client = begin(support, customer)
    session = ImpersonationSession.objects.get()
    assert session.actor == support and session.target == customer

    # The identity is swapped and the banner names both people, with an exit.
    me = client.get("/api/auth/me/")
    assert me.status_code == 200 and me.json()["email"] == "customer@example.com"
    page = client.get("/page/")
    body = page.content.decode()
    assert "karni-impersonation-banner" in body and body.endswith("</body></html>")
    assert page["Content-Length"] == str(len(page.content))
    assert "customer@example.com" in body and "support@example.com" in body
    assert f'action="{STOP}"' in body and "Stop impersonating" in body
    assert "minutes left" in body

    # A write is attributed to both: the row's history names the customer, the batch names support.
    created = client.post("/api/notes/", {"text": "from support"}, content_type="application/json")
    assert created.status_code == 201, created.content
    note = Note.objects.get(text="from support")
    assert note.created_by == customer
    entry = ChangeLog.objects.for_object(note).get()
    assert entry.actor == customer and entry.batch_id == session.batch_id
    assert entry.batch.actor == support and entry.batch.kind == "impersonation"

    # Blocked while impersonating: deleting, exporting, credential paths, whatever the customer may.
    deleted = client.delete(f"/api/notes/{note.pk}/")
    assert deleted.status_code == 403 and "IMP006" in deleted.json()["detail"]
    assert Note.objects.filter(pk=note.pk).exists()
    export = client.get("/api/notes/export/")
    assert export.status_code == 403
    password = client.post(
        "/api/auth/password/change/",
        {"current_password": "x", "new_password": "y"},
        content_type="application/json",
    )
    assert password.status_code == 403 and "IMP006" in password.json()["detail"]
    allowed = client.patch(
        f"/api/notes/{note.pk}/", {"text": "edited"}, content_type="application/json"
    )
    assert allowed.status_code == 200

    # The exit: one POST, back to where you were, as yourself, no banner.
    out = client.post(STOP, {"next": "/admin/"})
    assert out.status_code == 302 and out["Location"] == "/admin/"
    session.refresh_from_db()
    assert session.end_reason == "stopped" and session.ended_at is not None
    assert client.get("/api/auth/me/").json()["email"] == "support@example.com"
    assert "karni-impersonation-banner" not in client.get("/page/").content.decode()


def test_the_admin_blocks_deletes_and_dangerous_actions_while_impersonating(
    support: Any, customer: Any
) -> None:
    # The customer is given admin access to notes so the screens exist; the veto still blocks.
    customer.is_staff = True
    customer.save()
    from tests.conftest import grant_admin_perms

    grant_admin_perms(customer)
    client = begin(support, customer)
    note = Note.objects.create(text="theirs", created_by=customer)
    changelist = client.get(reverse("admin:testapp_note_changelist"))
    assert changelist.status_code == 200
    body = changelist.content.decode()
    assert "delete_selected" not in body and "export_csv" not in body
    assert client.get(reverse("admin:testapp_note_delete", args=[note.pk])).status_code == 403
    assert client.get(reverse("admin:testapp_note_import")).status_code == 403
    assert client.get(reverse("admin:testapp_note_change", args=[note.pk])).status_code == 200


def test_the_limit_ends_the_session_on_the_next_request(support: Any, customer: Any) -> None:
    client = begin(support, customer)
    session = ImpersonationSession.objects.get()
    ImpersonationSession.objects.filter(pk=session.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    me = client.get("/api/auth/me/")
    assert me.json()["email"] == "support@example.com"  # back to yourself
    session.refresh_from_db()
    assert session.end_reason == "expired"
    assert "karni-impersonation-banner" not in client.get("/page/").content.decode()


def test_logging_out_ends_the_session(support: Any, customer: Any) -> None:
    client = begin(support, customer)
    client.post("/api/auth/logout/", content_type="application/json")
    session = ImpersonationSession.objects.get()
    assert session.end_reason in ("logout", "stopped") and session.ended_at is not None


def test_the_user_admin_has_an_impersonate_button(support: Any, customer: Any) -> None:
    client = Client()
    client.force_login(support)
    change = client.get(reverse("admin:karni_accounts_user_change", args=[customer.pk]))
    assert change.status_code == 200
    url = reverse("admin:karni_accounts_user_impersonate", args=[customer.pk])
    assert url in change.content.decode()
    page = client.get(url)
    assert page.status_code == 200 and "customer@example.com" in page.content.decode()
    started = client.post(url, {"reason": "from the user page"})
    assert (
        started.status_code == 302
        and ImpersonationSession.objects.get().reason == "from the user page"
    )
