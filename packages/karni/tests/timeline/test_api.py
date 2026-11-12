"""GET /api/timeline/: whose timeline, the row scope per entry, paging, filters, query counts."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from karni import timeline
from karni.testing import client_as, deliver_now
from tests.helpdeskapp.models import Note, Ticket
from tests.helpdeskapp.services import open_ticket
from tests.loyaltyapp.services import log_visit

pytestmark = pytest.mark.django_db


def _titles(response: Any) -> list[str]:
    assert response.status_code == 200, response.data
    return [row["title"] for row in response.data["results"]]


@pytest.fixture
def story(cast: dict[str, Any]) -> dict[str, Any]:
    """Ines: a ticket (from an event), a visit (by hand), a call linked to Omar's ticket."""
    ines, omar = cast["ines"], cast["omar"]
    ticket = open_ticket(ines, "Boat booking")
    deliver_now()
    log_visit(ines, dt.date(2026, 11, 2), Decimal("18.40"))
    omar_ticket = Ticket.objects.create(person=omar, subject="Oars")
    timeline.record(
        kind="helpdeskapp.call",
        title="Called about both bookings",
        person=ines,
        subjects=[omar_ticket],
    )
    timeline.record(kind="helpdeskapp.note", title="Omar's note", person=omar)
    timeline.record(
        kind="helpdeskapp.club",
        title="Club renewed",
        subjects=[cast["org"]],
        occurred_at=timezone.now() - dt.timedelta(days=1),
    )
    return {**cast, "ticket": ticket, "omar_ticket": omar_ticket}


def test_a_person_sees_their_own_timeline_without_other_peoples_records(
    story: dict[str, Any],
) -> None:
    client = client_as(user=story["ines_user"])
    found = _titles(client.get("/api/timeline/", {"person": str(story["ines"].pk)}))
    # The call is linked to Omar's ticket, which Ines may not read: it stays hidden.
    assert found == ["Visited the club and spent 18.40", "Ticket opened: Boat booking"]
    row = client.get("/api/timeline/", {"person": str(story["ines"].pk)}).data["results"][1]
    assert row["links"] == [
        {"model": "helpdeskapp.ticket", "id": str(story["ticket"].pk), "resource": "tickets"}
    ]
    assert row["person"] == str(story["ines"].pk) and row["event"] is not None
    assert row["kind"] == "helpdeskapp.ticket.opened" and row["source"] == "helpdeskapp"


def test_another_persons_timeline_is_404(story: dict[str, Any]) -> None:
    client = client_as(user=story["ines_user"])
    response = client.get("/api/timeline/", {"person": str(story["omar"].pk)})
    assert response.status_code == 404
    missing = client.get("/api/timeline/", {"person": "00000000-0000-0000-0000-000000000000"})
    assert missing.status_code == 404  # the same answer: nothing says which exists
    assert client_as(None).get("/api/timeline/", {"person": str(story["ines"].pk)}).status_code in {
        401,
        403,
    }


def test_staff_see_what_their_grants_reach(story: dict[str, Any]) -> None:
    admin = client_as(user=story["admin"])
    assert _titles(admin.get("/api/timeline/", {"person": str(story["ines"].pk)})) == [
        "Called about both bookings",
        "Visited the club and spent 18.40",
        "Ticket opened: Boat booking",
    ]
    # The agent reads tickets and people, not visits.
    agent = client_as(user=story["agent"])
    assert _titles(agent.get("/api/timeline/", {"person": str(story["ines"].pk)})) == [
        "Called about both bookings",
        "Ticket opened: Boat booking",
    ]


def test_a_records_timeline_and_an_organisations(story: dict[str, Any]) -> None:
    agent = client_as(user=story["agent"])
    ref = f"helpdeskapp.ticket:{story['omar_ticket'].pk}"
    assert _titles(agent.get("/api/timeline/", {"subject": ref})) == ["Called about both bookings"]
    omar = client_as(user=story["omar_user"])
    # Omar reads his ticket, not Ines: the call is about her, so he does not see it.
    assert _titles(omar.get("/api/timeline/", {"subject": ref})) == []
    org = str(story["org"].pk)
    assert _titles(agent.get("/api/timeline/", {"organisation": org})) == ["Club renewed"]
    assert (
        client_as(user=story["omar_user"]).get("/api/timeline/", {"organisation": org}).status_code
        == 404
    )


def test_a_record_without_an_endpoint_is_for_superusers(story: dict[str, Any]) -> None:
    from tests.people.conftest import make_user

    note = Note.objects.create(subject=story["ines"], text="Prefers mornings.")
    timeline.record(kind="helpdeskapp.note", title="Noted", person=story["ines"], subjects=[note])
    agent = client_as(user=story["agent"])
    assert "Noted" not in _titles(agent.get("/api/timeline/", {"person": str(story["ines"].pk)}))
    root = make_user("root@example.com", is_staff=True, is_superuser=True)
    found = _titles(client_as(user=root).get("/api/timeline/", {"person": str(story["ines"].pk)}))
    assert "Noted" in found


@pytest.mark.parametrize(
    "query",
    [
        {},
        {"person": "x", "organisation": "y"},
        {"person": "not-a-key"},
        {"subject": "nope.model:1"},
        {"subject": "helpdeskapp.ticket"},
        {"person": "00000000-0000-0000-0000-000000000000", "cursor": "%%%"},
    ],
)
def test_a_malformed_query_is_e463(story: dict[str, Any], query: dict[str, str]) -> None:
    response = client_as(user=story["admin"]).get("/api/timeline/", query)
    assert response.status_code == 400 and response.data["code"] == "E463"


def test_kind_and_source_filters(story: dict[str, Any]) -> None:
    admin = client_as(user=story["admin"])
    person = str(story["ines"].pk)
    assert _titles(
        admin.get("/api/timeline/", {"person": person, "kind": "loyaltyapp.visit,crm.none"})
    ) == ["Visited the club and spent 18.40"]
    assert _titles(admin.get("/api/timeline/", {"person": person, "source": "loyaltyapp"})) == [
        "Visited the club and spent 18.40"
    ]


def _many(person: Any, count: int, *, hidden_every: int = 0, hidden_to: Any = None) -> None:
    now = timezone.now()
    for index in range(count):
        subjects = [hidden_to] if hidden_every and index % hidden_every == 0 else []
        timeline.record(
            kind="helpdeskapp.call",
            title=f"Call {index:03d}",
            person=person,
            subjects=subjects,
            occurred_at=now - dt.timedelta(minutes=index),
        )


def test_paging_walks_every_visible_entry_once(cast: dict[str, Any]) -> None:
    hidden = Ticket.objects.create(person=cast["omar"], subject="Not hers")
    _many(cast["ines"], 23, hidden_every=3, hidden_to=hidden)
    client = client_as(user=cast["ines_user"])
    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        query = {"person": str(cast["ines"].pk), "limit": 4}
        if cursor:
            query["cursor"] = cursor
        response = client.get("/api/timeline/", query)
        titles = _titles(response)
        assert len(titles) <= 4
        seen.extend(titles)
        cursor = response.data["next"]
        pages += 1
        if cursor is None:
            break
    expected = [f"Call {i:03d}" for i in range(23) if i % 3 != 0]
    assert seen == expected and pages >= 4


def test_the_limit_is_bounded(cast: dict[str, Any], settings: Any) -> None:
    settings.KARNI_TIMELINE_MAX_PAGE_SIZE = 5
    _many(cast["ines"], 8)
    client = client_as(user=cast["ines_user"])
    response = client.get("/api/timeline/", {"person": str(cast["ines"].pk), "limit": 500})
    assert len(_titles(response)) == 5 and response.data["next"] is not None


def _count(client: Any, query: dict[str, Any]) -> int:
    with CaptureQueriesContext(connection) as queries:
        response = client.get("/api/timeline/", query)
    assert response.status_code == 200
    return len(queries)


def test_the_list_costs_the_same_for_3_or_30_entries(cast: dict[str, Any]) -> None:
    def fill(count: int) -> None:
        for index in range(count):
            ticket = Ticket.objects.create(person=cast["ines"], subject=f"T{index}")
            visit = log_visit(cast["ines"], dt.date(2026, 11, 1), Decimal("1"))
            timeline.record(
                kind="helpdeskapp.call",
                title=f"Call {index}",
                person=cast["ines"],
                subjects=[ticket, visit, cast["org"]],
            )

    query = {"person": str(cast["ines"].pk), "limit": 100}
    fill(3)
    client = client_as(user=cast["ines_user"])
    _count(client, query)  # warm the content type cache
    few = _count(client, query)
    fill(27)
    many = _count(client, query)
    assert many == few
