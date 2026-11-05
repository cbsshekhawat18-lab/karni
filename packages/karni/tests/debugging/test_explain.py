"""``karni queries --explain`` (experimental): EXPLAIN ANALYZE, rolled back, and the scans to fix.

The analysis runs on PostgreSQL only (CI's PostgreSQL step). On SQLite the
command keeps its plain EXPLAIN and says so (W610).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.db import connection

from karni.api import diagnose
from karni.api.explain import SeqScan, explain_analyze, render_plan, suggest_index
from tests.perfapp.models import Chapter
from tests.testapp.models import Event, Venue

pytestmark = pytest.mark.django_db
postgres = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="EXPLAIN ANALYZE is read on PostgreSQL only"
)


def _events(count: int) -> None:
    from django.utils import timezone

    venue = Venue.objects.create(name="Hall")
    now = timezone.now()
    Event.objects.bulk_create(
        Event(
            title=f"Event {n}",
            status="published" if n % 50 == 0 else "draft",
            venue=venue,
            starts_at=now,
        )
        for n in range(count)
    )


def _query(sql: str, params: list[object]) -> SimpleNamespace:
    return SimpleNamespace(sql=sql, params=params, control=False)


def test_the_index_named_for_a_filter() -> None:
    index, why = suggest_index(
        Event, "(((status)::text = 'draft'::text) AND (deleted_at IS NULL))", ()
    )
    assert index == (
        'models.Index(fields=["status"], name="event_status_idx", '
        "condition=Q(deleted_at__isnull=True))"
    )
    assert not why
    index, _ = suggest_index(Event, "((venue_id = 3) AND (starts_at > now()))")
    assert index.startswith('models.Index(fields=["venue", "starts_at"], name="event_venue_')
    trigram, _ = suggest_index(Event, "((title)::text ~~* '%gala%'::text)")
    assert trigram.startswith('GinIndex(fields=["title"], opclasses=["gin_trgm_ops"]')
    # icontains on PostgreSQL is UPPER(title) LIKE UPPER(...): the index is on UPPER(title)
    search, _ = suggest_index(
        Event, "((deleted_at IS NULL) AND (upper((title)::text) ~~ '%GALA%'::text))"
    )
    assert search.startswith('GinIndex(OpClass(Upper("title"), name="gin_trgm_ops")')
    assert "condition=Q(deleted_at__isnull=True)" in search
    by_sort, _ = suggest_index(Event, "", ["testapp_event.starts_at DESC"])
    assert by_sort.startswith('models.Index(fields=["-starts_at"]')
    none, why = suggest_index(Event, "(random() < 0.5)")
    assert none == "" and why == "no column of the filter can lead an index"
    assert len(suggest_index(Chapter, "((novel_id = 1) AND (number = 2) AND (title = 'x'))")[0])


def test_a_plan_renders_as_text() -> None:
    plan = {
        "Node Type": "Limit",
        "Actual Rows": 10,
        "Actual Loops": 1,
        "Actual Total Time": 1.5,
        "Plans": [
            {
                "Node Type": "Seq Scan",
                "Relation Name": "testapp_event",
                "Actual Rows": 10,
                "Actual Loops": 1,
                "Actual Total Time": 1.2,
                "Filter": "(status = 'draft')",
                "Rows Removed by Filter": 990,
            }
        ],
    }
    assert render_plan(plan).splitlines() == [
        "Limit (actual rows=10 loops=1 time=1.500ms)",
        "  Seq Scan on testapp_event (actual rows=10 loops=1 time=1.200ms)",
        "    Filter: (status = 'draft')",
        "    Rows Removed by Filter: 990",
    ]


def test_a_finding_reads_as_one_line() -> None:
    scan = SeqScan(
        "testapp_event", 5000, 5000, 100, "SELECT ...", "(status = 'draft')", (), "Event",
        index='models.Index(fields=["status"], name="event_status_idx")',
    )  # fmt: skip
    assert scan.line() == (
        "W611 Seq Scan on testapp_event (5,000 rows, 5,000 read, 100 kept) for "
        '(status = \'draft\'): add models.Index(fields=["status"], name="event_status_idx") '
        "to Event.Meta.indexes"
    )
    assert scan.as_dict()["code"] == "W611"


@postgres
def test_a_sequential_scan_on_a_large_table_is_flagged_with_its_index(settings) -> None:
    settings.KARNI_EXPLAIN_SEQ_SCAN_ROWS = 1000
    _events(1500)
    sql = 'SELECT "testapp_event"."id" FROM "testapp_event" WHERE "testapp_event"."status" = %s'
    found = explain_analyze([_query(sql, ["published"]), _query(sql, ["published"])])
    assert len(found.plans) == 1  # each distinct statement once
    assert "Seq Scan on testapp_event (actual rows=30" in found.plans[0][1]
    assert "Execution Time:" in found.plans[0][1]
    (scan,) = found.scans
    assert (scan.table, scan.rows, scan.scanned, scan.kept) == ("testapp_event", 1500, 1500, 30)
    assert scan.index.startswith('models.Index(fields=["status"]')
    assert scan.model == "Event"


@postgres
def test_a_filter_that_keeps_most_rows_wants_no_index(settings) -> None:
    settings.KARNI_EXPLAIN_SEQ_SCAN_ROWS = 1000
    _events(1500)
    sql = 'SELECT "testapp_event"."id" FROM "testapp_event" WHERE "testapp_event"."status" = %s'
    (scan,) = explain_analyze([_query(sql, ["draft"])]).scans
    assert not scan.index and "keeps 98% of the rows read" in scan.why


@postgres
def test_small_tables_are_not_flagged(settings) -> None:
    settings.KARNI_EXPLAIN_SEQ_SCAN_ROWS = 1000
    _events(20)
    sql = 'SELECT "testapp_event"."id" FROM "testapp_event" WHERE "testapp_event"."status" = %s'
    found = explain_analyze([_query(sql, ["published"])])
    assert found.plans and not found.scans


@postgres
def test_explain_runs_inside_the_rolled_back_request(settings) -> None:
    settings.KARNI_EXPLAIN_SEQ_SCAN_ROWS = 1000
    _events(1500)
    with connection.cursor() as cursor:  # no index to use: the planner must read the table
        cursor.execute("SET LOCAL enable_indexscan = off")
        cursor.execute("SET LOCAL enable_bitmapscan = off")
        cursor.execute("SET LOCAL enable_indexonlyscan = off")
    report = diagnose.run("/api/events/", explain=True)
    assert report.status == 200 and report.plans
    assert all("(no plan" not in plan for _sql, plan in report.plans)
    assert report.scans and all(scan.rows >= 1000 for scan in report.scans)
    text = report.render()
    assert "Sequential scans on large tables (" in text and "W611 Seq Scan on testapp_event" in text
    assert any("EXPLAIN ANALYZE of" in note for note in report.notes)
    listed = next(scan for scan in report.scans if scan.sort)
    assert listed.index.startswith('models.Index(fields=["-created_at"]')
    assert listed.index.endswith("condition=Q(deleted_at__isnull=True))")
    counted = next(scan for scan in report.scans if not scan.sort)
    assert "keeps 100% of the rows read" in counted.why
    data = report.as_dict()
    assert data["seq_scans"] and data["seq_scans"][0]["table"] == "testapp_event"
    assert Event.objects.count() == 1500  # what ANALYZE ran changed nothing


@pytest.mark.skipif(connection.vendor == "postgresql", reason="the note for other databases")
def test_other_databases_keep_plain_explain_and_say_so() -> None:
    _events(5)
    report = diagnose.run("/api/events/", explain=True)
    assert report.plans and not report.scans
    note = next(note for note in report.notes if note.startswith("W610 "))
    assert "PostgreSQL only" in note and f"This database is {connection.vendor}" in note
