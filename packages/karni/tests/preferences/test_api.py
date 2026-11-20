"""The API behind the Settings page: who may open and change what, locks, errors, history."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APIClient

from karni import preferences

pytestmark = pytest.mark.django_db


def _client(user: Any = None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


def test_the_page_answers_details_sections_connections_and_emails(admin: Any) -> None:
    response = _client(admin).get("/api/preferences/")
    assert response.status_code == 200, response.content
    page = response.json()
    assert page["contract"] == preferences.CONTRACT
    assert page["details"]["can_change"] and page["details"]["values"]["currency_display"]
    assert {f["name"] for f in page["details"]["fields"]} >= {"name", "logo", "time_zone"}
    desk = next(s for s in page["sections"] if s["key"] == "helpdeskapp")
    assert desk["title"] == "Help desk" and desk["values"]["reply_within_hours"] == 24
    assert desk["schema"]["properties"]["reply_within_hours"]["maximum"] == 168
    connections = {c["name"]: c for c in page["connections"]["items"]}
    assert connections["helpdeskapp.ticket_timeline"]["active"] is True
    paid = connections["loyaltyapp.paid_visits"]
    assert paid["installed"] is False and paid["on"] is True and paid["active"] is False
    assert paid["needs"] == ["karni_payments"] and paid["part"] == "loyaltyapp"
    kinds = {k["name"]: k for k in page["emails"]["items"]}
    assert kinds["rulesapp.purchase_paid"]["source"] == "rules"
    assert kinds["helpdeskapp.ticket_closed"]["on"] is True


def test_who_may_open_and_change_what(office: Any, lead: Any, customer: Any) -> None:
    assert _client().get("/api/preferences/").status_code in (401, 403)
    assert _client(customer).get("/api/preferences/").status_code == 403
    page = _client(office).get("/api/preferences/").json()
    desk = next(s for s in page["sections"] if s["key"] == "helpdeskapp")
    assert page["details"]["can_change"] and not desk["can_change"]
    assert not page["connections"]["can_change"]
    assert _client(lead).get("/api/preferences/").status_code == 200  # by role:desk-lead

    patch = _client(office).patch
    assert patch("/api/preferences/details/", {"name": "Harbour"}, format="json").status_code == 200
    assert (
        patch("/api/preferences/sections/helpdeskapp/", {"greeting": "Hi"}, format="json")
    ).status_code == 403
    on = {"on": False}
    assert (
        patch("/api/preferences/connections/helpdeskapp.ticket_timeline/", on, format="json")
    ).status_code == 403
    lead_patch = _client(lead).patch
    found = lead_patch("/api/preferences/sections/helpdeskapp/", {"greeting": "Hi"}, format="json")
    assert found.status_code == 200 and found.json()["values"]["greeting"] == "Hi"
    assert lead_patch("/api/preferences/details/", {"name": "x"}, format="json").status_code == 403


def test_refusals_answer_their_codes(admin: Any) -> None:
    patch = _client(admin).patch
    bad = patch("/api/preferences/sections/helpdeskapp/", {"priority": "urgent"}, format="json")
    assert bad.status_code == 400 and bad.json()["code"] == "E323"
    assert "priority" in bad.json()["errors"]
    missing = patch("/api/preferences/sections/shop/", {"x": 1}, format="json")
    assert missing.status_code == 404 and missing.json()["code"] == "E325"
    unknown = patch("/api/preferences/connections/nobody.this/", {"on": True}, format="json")
    assert unknown.status_code == 404
    wrong = patch("/api/preferences/emails/helpdeskapp.ticket_closed/", {"on": "no"}, format="json")
    assert wrong.status_code == 400
    zone = patch("/api/preferences/details/", {"time_zone": "Mars/Olympus"}, format="json")
    assert zone.status_code == 400 and "time_zone" in zone.json()["errors"]
    with override_settings(KARNI_PREFERENCES_LOCKED={"details": {"name": "Fixed"}}):
        locked = patch("/api/preferences/details/", {"name": "Mine"}, format="json")
        assert locked.status_code == 409 and locked.json()["code"] == "E324"
        page = _client(admin).get("/api/preferences/").json()
        assert page["details"]["locked"] == ["name"]
        assert page["details"]["values"]["name"] == "Fixed"


def test_switches_change_and_go_back_to_their_default(admin: Any) -> None:
    patch = _client(admin).patch
    url = "/api/preferences/connections/loyaltyapp.visit_events/"
    assert patch(url, {"on": True}, format="json").json() == {
        "name": "loyaltyapp.visit_events",
        "on": True,
    }
    assert preferences.active("loyaltyapp.visit_events")
    assert patch(url, {"on": None}, format="json").json()["on"] is False
    email = "/api/preferences/emails/rulesapp.purchase_cancelled/"
    assert patch(email, {"on": False}, format="json").json()["on"] is False
    assert not preferences.email_on("rulesapp.purchase_cancelled")


def test_a_logo_is_uploaded_and_removed(admin: Any, tmp_path: Any) -> None:
    with override_settings(MEDIA_ROOT=str(tmp_path)):
        client = _client(admin)
        logo = SimpleUploadedFile("logo.png", b"\x89PNG\r\n\x1a\n", content_type="image/png")
        sent = client.patch("/api/preferences/details/", {"logo": logo}, format="multipart")
        assert sent.status_code == 200, sent.content
        assert "preferences/logo" in sent.json()["values"]["logo"]
        public = _client().get("/api/preferences/public/").json()
        assert public["logo"] == sent.json()["values"]["logo"]
        gone = client.patch("/api/preferences/details/", {"logo": None}, format="json")
        assert gone.json()["values"]["logo"] == ""
        exe = SimpleUploadedFile("logo.exe", b"MZ", content_type="application/octet-stream")
        refused = client.patch("/api/preferences/details/", {"logo": exe}, format="multipart")
        assert refused.status_code == 400 and "logo" in refused.json()["errors"]


def test_the_public_details_answer_anyone_and_hide_the_sender(admin: Any) -> None:
    preferences.save_details(
        {"name": "Harbour Yoga", "phone": "+44 20 7946 0000", "sender_email": "x@harbour.example"}
    )
    found = _client().get("/api/preferences/public/").json()
    assert found["name"] == "Harbour Yoga" and found["phone"] == "+44 20 7946 0000"
    assert "sender_email" not in found and found["currency_display"] == "symbol"


def test_history_lists_the_changes_with_who_made_them(admin: Any, customer: Any) -> None:
    client = _client(admin)
    client.patch("/api/preferences/details/", {"name": "Harbour"}, format="json")
    client.patch("/api/preferences/sections/helpdeskapp/", {"greeting": "Hi"}, format="json")
    client.patch(
        "/api/preferences/connections/helpdeskapp.ticket_timeline/", {"on": False}, format="json"
    )
    rows = client.get("/api/preferences/history/").json()
    assert {(r["table"], r["record"]) for r in rows} == {
        ("Details", "details"),
        ("SectionValue", "helpdeskapp"),
        ("Switch", "helpdeskapp.ticket_timeline"),
    }
    assert all(r["actor"] == str(admin) for r in rows)
    assert _client(customer).get("/api/preferences/history/").status_code == 403


def test_the_page_reads_each_table_once_per_request(
    admin: Any, django_assert_max_num_queries: Any
) -> None:
    preferences.save_section("helpdeskapp", {"greeting": "Hi"})
    client = _client(admin)
    client.get("/api/preferences/")  # warm the content types and grants
    with django_assert_max_num_queries(12):
        assert client.get("/api/preferences/").status_code == 200
