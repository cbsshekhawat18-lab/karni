"""Tier 4 audit, item 1: N+1 on a three-level nested list (Booking -> Event -> Venue).

Run with ``pytest -s`` so the captured SQL is printed.
"""

from __future__ import annotations

import re

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from karni.testing import client_as
from karni.testing.factories import create

from events.models import Booking, Event, Venue

pytestmark = pytest.mark.django_db

EXPAND = "?expand=event.venue,event.organizer"


def _seed(user, n: int) -> None:
    for i in range(n):
        venue = create(Venue, name=f"venue-{i}", city=f"city-{i}")
        event = create(Event, title=f"event-{i}", organizer=user, venue=venue)
        create(Booking, event=event, attendee=user, quantity=i + 1)


def _show(label: str, ctx: CaptureQueriesContext, response) -> None:
    print(f"\n=== {label}: {len(ctx.captured_queries)} queries, "
          f"HTTP {response.status_code}, X-Karni-Queries={response.get('X-Karni-Queries')}, "
          f"X-Karni-Query-Budget={response.get('X-Karni-Query-Budget')}")
    for i, q in enumerate(ctx.captured_queries, 1):
        sql = re.sub(r"\s+", " ", q["sql"])
        print(f"  {i:>2}. {sql[:260]}")


def _list(client, path: str, label: str):
    with CaptureQueriesContext(connection) as ctx:
        response = client.get(path)
    _show(label, ctx, response)
    return ctx, response


def test_generated_bookings_list_three_levels_deep_is_flat():
    """BookingViewSet (optimiser on): the query count must not grow with rows."""
    client = client_as("attendee")
    user = client.user
    _seed(user, 2)
    ctx2, r2 = _list(client, "/api/bookings/" + EXPAND, "BookingViewSet.list, 2 rows, expand=event.venue,event.organizer")
    assert r2.status_code == 200
    _seed(user, 10)
    ctx12, r12 = _list(client, "/api/bookings/" + EXPAND, "BookingViewSet.list, 12 rows, expand=event.venue,event.organizer")
    assert r12.status_code == 200
    rows = r12.json()["results"]
    assert len(rows) == 12
    print("first row:", rows[0])
    assert rows[0]["event"]["venue"]["name"].startswith("venue-"), rows[0]
    sql = " ".join(q["sql"] for q in ctx12.captured_queries)
    # Event's read scope is Owned('organizer') -> a scoped Prefetch (ADR 0001 R3), and inside it
    # venue (Public) is a JOIN; so: one booking SELECT + one event SELECT joining venue.
    assert re.search(r'FROM "events_event" INNER JOIN "karni_accounts_user" .* INNER JOIN "events_venue"', sql), sql
    assert "events_event\".\"id\" IN" in sql, sql  # one scoped Prefetch for all 12 events
    # the first request also resolves the user's grants once (RolePermission); ignore it
    data2 = [q for q in ctx2.captured_queries if "rolepermission" not in q["sql"]]
    data12 = [q for q in ctx12.captured_queries if "rolepermission" not in q["sql"]]
    assert len(data12) == len(data2), f"grew from {len(data2)} to {len(data12)} queries"
    print(f"\nRESULT: optimised list is flat — {len(data2)} data queries at 2 rows, "
          f"{len(data12)} at 12 rows (plus one one-off grants lookup on the first request)")


def test_hand_viewset_without_optimiser_fails_the_budget():
    """SlowBookingViewSet (optimize = False): the same request must blow the list budget (8)."""
    from karni.performance import QueryBudgetExceeded

    client = client_as("attendee")
    _seed(client.user, 12)
    with CaptureQueriesContext(connection) as ctx:
        with pytest.raises(QueryBudgetExceeded) as excinfo:
            client.get("/api/slow-bookings/" + EXPAND)
    print(f"\n=== SlowBookingViewSet.list, 12 rows: {len(ctx.captured_queries)} queries; "
          f"raised {type(excinfo.value).__name__} code={excinfo.value.code}")
    print("--- failure text ---")
    print(str(excinfo.value))
    print("--- end ---")


def test_hand_viewset_without_optimiser_n_plus_one_unguarded():
    """DELIBERATELY FAILING: the same request without catching the exception — what pytest shows."""
    client = client_as("attendee")
    _seed(client.user, 12)
    client.get("/api/slow-bookings/" + EXPAND)
