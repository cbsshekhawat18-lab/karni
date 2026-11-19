"""karni.notify over HTTP: the inbox, a person's switches, the unsubscribe link, the editor."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from django.core import mail
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from karni import notify
from karni.notify.models import EmailTemplate, Notification, Unsubscribe
from tests.notify.conftest import RECEIPT_FIELDS, as_user

pytestmark = pytest.mark.django_db


def _notes(user: Any, count: int) -> None:
    for number in range(count):
        notify.send("club.note", to=[user], context={"who": f"Lee {number}"})


def test_the_inbox_lists_the_callers_own_newest_first(ana: Any, ben: Any) -> None:
    _notes(ana, 3)
    _notes(ben, 1)
    answer = as_user(ana).get("/api/inbox/")
    assert answer.status_code == 200
    assert answer.data["count"] == 3 and answer.data["unread"] == 3
    assert [row["title"] for row in answer.data["results"]][0] == "A note from Lee 2"
    assert all(row["read"] is False for row in answer.data["results"])
    assert APIClient().get("/api/inbox/").status_code in (401, 403)


def test_the_inbox_pages_filters_and_stays_at_a_few_queries(ana: Any) -> None:
    _notes(ana, 30)
    notify.send("club.receipt", to=[ana], context={"order": {"number": 7}, "link": "/o/7"})
    with CaptureQueriesContext(connection) as queries:
        first = as_user(ana).get("/api/inbox/?limit=10")
    assert len(queries) <= 6
    assert len(first.data["results"]) == 10 and first.data["next"] == 2
    last = as_user(ana).get("/api/inbox/?limit=10&page=4")
    assert len(last.data["results"]) == 1 and last.data["next"] is None
    only = as_user(ana).get("/api/inbox/?kind=club.receipt")
    assert [row["link"] for row in only.data["results"]] == ["/o/7"]
    beyond = as_user(ana).get("/api/inbox/?page=9")
    assert beyond.status_code == 400 and beyond.data["code"] == "E444"


def test_mark_read_unread_and_all(ana: Any, ben: Any) -> None:
    _notes(ana, 2)
    _notes(ben, 1)
    mine = Notification.objects.filter(recipient=ana).first()
    theirs = Notification.objects.get(recipient=ben)
    assert mine is not None
    read = as_user(ana).post(f"/api/inbox/{mine.pk}/read/")
    assert read.status_code == 200 and read.data["read"] is True
    assert as_user(ana).get("/api/inbox/unread/").data == {"count": 1}
    assert as_user(ana).get("/api/inbox/?unread=true").data["count"] == 1
    assert as_user(ana).post(f"/api/inbox/{theirs.pk}/read/").status_code == 404
    unread = as_user(ana).post(f"/api/inbox/{mine.pk}/unread/")
    assert unread.data["read"] is False
    assert as_user(ana).post("/api/inbox/read-all/").data == {"updated": 2}
    assert as_user(ben).get("/api/inbox/unread/").data == {"count": 1}


def test_a_person_lists_and_switches_their_own_kinds(ana: Any) -> None:
    rows = {row["kind"]: row for row in as_user(ana).get("/api/inbox/choices/").data}
    assert "club.code" not in rows  # nobody may switch a sign-in code off
    assert rows["club.receipt"]["channels"] == ["email", "inbox"]
    assert rows["club.note"]["channels"] == ["inbox"]
    assert rows["club.news"]["marketing"] is True
    changed = as_user(ana).patch(
        "/api/inbox/choices/club.receipt/", {"email": False}, format="json"
    )
    assert changed.status_code == 200
    assert (changed.data["email"], changed.data["inbox"]) == (False, True)
    refused = as_user(ana).patch("/api/inbox/choices/club.code/", {"email": False}, format="json")
    assert refused.status_code == 400 and refused.data["code"] == "E441"


def test_the_unsubscribe_link_works_without_signing_in(ana: Any) -> None:
    notify.send("club.news", to=[ana])
    link = mail.outbox[0].extra_headers["List-Unsubscribe"].strip("<>")
    token = parse_qs(urlparse(link).query)["token"][0]
    anyone = APIClient()
    seen = anyone.get("/api/notify/unsubscribe/", {"token": token})
    assert seen.status_code == 200
    assert seen.json()["address"] == "ana@example.com" and seen.json()["unsubscribed"] is False
    assert not Unsubscribe.objects.exists()  # a GET never unsubscribes (link scanners)
    page = anyone.get("/api/notify/unsubscribe/", {"token": token}, HTTP_ACCEPT="text/html")
    assert b"Stop sending" in page.content and b"Club news" in page.content
    # a mail program's one-click: POST with the token in the address
    clicked = anyone.post(
        f"/api/notify/unsubscribe/?token={token}",
        "List-Unsubscribe=One-Click",
        content_type="application/x-www-form-urlencoded",
    )
    assert clicked.status_code == 200 and clicked.json()["unsubscribed"] is True
    assert notify.unsubscribed("ana@example.com", "club.news")
    back = anyone.post(f"/api/notify/unsubscribe/?token={token}&undo=1")
    assert back.json()["unsubscribed"] is False
    forged = anyone.get("/api/notify/unsubscribe/", {"token": token + "x"})
    assert forged.status_code == 400 and forged.json()["code"] == "E442"


def test_the_email_editor_lists_edits_previews_and_puts_back(writer: Any, ana: Any) -> None:
    rows = as_user(writer).get("/api/email-templates/")
    assert rows.status_code == 200
    receipt = next(row for row in rows.data if row["kind"] == "club.receipt")
    assert receipt["edited"] is False and receipt["subject"] == "Receipt {{ order.number }}"
    assert receipt["channels"] == ["email", "inbox"] and receipt["marketing"] is False
    assert {"name": "order.number", "meaning": RECEIPT_FIELDS["order.number"]} in receipt["fields"]
    assert as_user(ana).get("/api/email-templates/").status_code == 403
    bad = as_user(writer).put(
        "/api/email-templates/club.receipt/",
        {"subject": "Hi", "text": "{% load static %}"},
        format="json",
    )
    assert bad.status_code == 400 and "text" in bad.data
    preview = as_user(writer).post(
        "/api/email-templates/club.receipt/preview/",
        {"subject": "Order {{ order.number }}", "text": "{{ order.total }}"},
        format="json",
    )
    assert preview.status_code == 200 and preview.data["subject"] == "Order [order.number]"
    saved = as_user(writer).put(
        "/api/email-templates/club.receipt/",
        {"subject": "Thanks for {{ order.number }}", "text": "Total {{ order.total }}"},
        format="json",
    )
    assert saved.status_code == 200 and saved.data["edited"] is True
    notify.send("club.receipt", to=[ana], context={"order": {"number": 5, "total": "9.00"}})
    assert mail.outbox[0].subject == "Thanks for 5" and mail.outbox[0].body == "Total 9.00"
    back = as_user(writer).delete("/api/email-templates/club.receipt/")
    assert back.data["edited"] is False and not EmailTemplate.objects.exists()
    assert as_user(writer).get("/api/email-templates/nope.kind/").status_code == 404


def test_the_schema_documents_the_inbox_and_the_editor(capsys: pytest.CaptureFixture[str]) -> None:
    from drf_spectacular.generators import SchemaGenerator

    schema = SchemaGenerator(urlconf="tests.notify.urls").get_schema(request=None, public=True)
    paths = schema["paths"]
    assert paths["/api/inbox/"]["get"]["operationId"] == "inbox_list"
    assert {"/api/inbox/unread/", "/api/inbox/read-all/", "/api/inbox/choices/"} <= set(paths)
    assert "patch" in paths["/api/inbox/choices/{kind}/"]
    assert "put" in paths["/api/email-templates/{kind}/"]
    assert "/api/notify/unsubscribe/" not in paths  # a page for people, not the API
    assert "Warning" not in capsys.readouterr().err


def test_the_api_mounts_the_routes_by_the_switch() -> None:
    from django.test import override_settings

    from karni.api.urls import _notify_urlpatterns

    with override_settings(KARNI_NOTIFY_API=True):
        names = {pattern.name for pattern in _notify_urlpatterns()}
    assert {"karni-inbox", "karni-inbox-unread", "karni-notify-unsubscribe"} <= names
    with override_settings(KARNI_NOTIFY_API=False):
        assert _notify_urlpatterns() == []


def test_the_admin_checks_an_edit_and_keeps_the_inbox_read_only() -> None:
    from django.contrib import admin as django_admin
    from django.test import RequestFactory

    from karni.notify.admin import EmailTemplateForm

    bad = EmailTemplateForm(data={"kind": "club.receipt", "subject": "Hi", "text": "{% load x %}"})
    assert not bad.is_valid() and "text" in bad.errors
    good = EmailTemplateForm(data={"kind": "club.receipt", "subject": "Hi", "text": "{{ link }}"})
    assert good.is_valid(), good.errors
    request = RequestFactory().get("/")
    inbox = django_admin.site._registry[Notification]
    assert not inbox.has_add_permission(request) and not inbox.has_change_permission(request)
