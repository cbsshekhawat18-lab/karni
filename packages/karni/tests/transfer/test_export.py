"""Export: the list as a file — filters, row scope and field visibility all apply."""

from __future__ import annotations

import io
from typing import Any

import pytest
from django.utils import timezone

from karni.middleware import current_user
from karni.transfer.formats import read_table
from tests.testapp.models import Customer, Event, Tag
from tests.transfer.conftest import EventViewSet, api_request, call, read_csv

pytestmark = pytest.mark.django_db


def _event(title: str, venue: Any, organizer: Any, **extra: Any) -> Event:
    with current_user(organizer):
        return Event.objects.create(
            title=title, starts_at=timezone.now(), venue=venue, organizer=organizer, **extra
        )


def _export(user: Any, **query: Any) -> Any:
    request = api_request("get", "/events/export/", user, query)
    return call(EventViewSet, {"get": "export"}, request)


def test_csv_export_follows_the_requests_filters_and_scope(make_user: Any, venues: Any) -> None:
    staff = make_user("staff@example.com", "staff")
    alice = make_user("alice@example.com", "organizer")
    bob = make_user("bob@example.com", "organizer")
    _event("Alice at the Arena", venues["arena"], alice)
    _event("Alice at the Hall", venues["hall"], alice, status=Event.Status.PUBLISHED)
    _event("Bob at the Arena", venues["arena"], bob)

    everything = _export(staff)
    assert everything.status_code == 200
    assert everything["Content-Type"].startswith("text/csv")
    assert 'filename="events.csv"' in everything["Content-Disposition"]
    rows = read_csv(everything)
    header, *data = rows
    assert header[:2] == ["id", "created_at"] and "venue" in header and "title" in header
    assert "internal_note" not in header  # write-only never exports
    assert len(data) == 3
    venue_col, title_col = header.index("venue"), header.index("title")
    assert {row[venue_col] for row in data} == {"Arena", "Hall"}  # natural key, not the pk

    filtered = read_csv(_export(staff, status="published"))
    assert [row[title_col] for row in filtered[1:]] == ["Alice at the Hall"]
    searched = read_csv(_export(staff, search="Bob"))
    assert [row[title_col] for row in searched[1:]] == ["Bob at the Arena"]
    ordered = read_csv(_export(staff, ordering="title"))
    assert [row[title_col] for row in ordered[1:]] == sorted(row[title_col] for row in data)

    mine = read_csv(_export(alice))
    assert {row[title_col] for row in mine[1:]} == {"Alice at the Arena", "Alice at the Hall"}
    assert everything["X-Karni-Export-Rows"] == "3"


def test_xlsx_export_is_a_workbook_with_the_same_rows(make_user: Any, venues: Any) -> None:
    staff = make_user("staff@example.com", "staff")
    tag = Tag.objects.create(name="music")
    event = _event("Gig", venues["arena"], staff)
    event.tags.add(tag)
    response = _export(staff, format="xlsx")
    assert response.status_code == 200
    assert response["Content-Type"].endswith("spreadsheetml.sheet")
    headers, rows = read_table(io.BytesIO(response.content), "xlsx")
    assert headers and len(rows) == 1
    assert rows[0][headers.index("title")] == "Gig"
    assert rows[0][headers.index("tags")] == "music"
    assert rows[0][headers.index("organizer")] == "staff@example.com"


def test_export_hides_the_fields_the_role_may_not_see(make_user: Any) -> None:
    from karni.api import Access, Authenticated, BaseViewSet

    class CustomerViewSet(BaseViewSet):
        model = Customer
        access = Access(read=Authenticated(), write=Authenticated())

    member = make_user("member@example.com", "user")
    staff = make_user("staff@example.com", "staff")
    Customer.objects.create(name="Ada", phone="123", salary=10)
    for user, visible in ((member, False), (staff, True)):
        request = api_request("get", "/customers/export/", user)
        response = call(CustomerViewSet, {"get": "export"}, request)
        header = read_csv(response)[0]
        assert ("salary" in header) is visible and ("phone" in header)


def test_an_unknown_format_or_too_many_rows_is_refused(make_user: Any, settings: Any) -> None:
    staff = make_user("staff@example.com", "staff")
    bad = _export(staff, format="pdf")
    assert bad.status_code == 404  # DRF's own answer to an unknown ?format=
    _event("one", None, staff)
    _event("two", None, staff)
    settings.KARNI_EXPORT_MAX_ROWS = 1
    capped = _export(staff)
    assert capped.status_code == 400 and "E803" in str(capped.data)


def test_export_needs_the_read_gate(make_user: Any) -> None:
    nobody = make_user("nobody@example.com")
    assert _export(nobody).status_code == 403


def test_a_nested_relation_exports_like_a_plain_one(make_user: Any, venues: Any) -> None:
    """A serializer that nests related rows (many=True or one) exports their natural keys.

    The rows come back as dicts, which the export used to collect into a set:
    ``TypeError: unhashable type: 'dict'``.
    """
    from rest_framework import serializers

    from karni.transfer.exports import export_rows

    staff = make_user("staff@example.com", "staff")
    event = _event("Tagged", venues["arena"], staff)
    event.tags.set([Tag.objects.create(name="music"), Tag.objects.create(name="outdoor")])

    class TagOut(serializers.ModelSerializer[Tag]):
        class Meta:
            model = Tag
            fields = ("id", "name")

    class VenueOut(serializers.ModelSerializer[Any]):
        class Meta:
            model = type(venues["arena"])
            fields = ("id", "name")

    class EventOut(serializers.ModelSerializer[Event]):
        tags = TagOut(many=True, read_only=True)
        venue = VenueOut(read_only=True)

        class Meta:
            model = Event
            fields = ("id", "title", "venue", "tags")

    request = api_request("get", "/events/export/", staff, {})
    header, row = export_rows(Event.objects.filter(pk=event.pk), EventOut, {"request": request})
    assert sorted(row[header.index("tags")]) == ["music", "outdoor"]
    assert row[header.index("venue")] == "Arena"
