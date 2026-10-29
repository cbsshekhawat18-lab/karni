"""Imports and ``karni load`` on integer keys (BigIntBaseModel, experimental).

``Part`` (an integer key and a natural key made of digits) and ``Reading``
(an integer key, no natural key) are integer-keyed whatever ``KARNI_TEST_PK``
says. What is pinned here:

* a relation cell names a target by its natural key alone, so a numeric part
  number is never read as a primary key;
* the ``id`` column matches existing rows only with ``match_ids``, and an id
  the scope does not hold is refused with one message, existing or not;
* ``keep_ids`` creates rows with the file's ids and moves the database
  sequence past them, so the next normal insert works (the reason to run
  this on PostgreSQL), and only a role that may create rows anywhere may use
  it;
* ``karni load`` writes legacy integer ids and moves the sequence on too.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from django.utils import timezone

from karni.exceptions import KarniValueError
from karni.middleware import current_user
from karni.transfer.imports import Importer, advance_sequences
from karni.transfer.loading import load_content
from karni.transfer.services import COMMIT, PREVIEW, create_job, run_stage, set_mapping
from tests.testapp.models import Event, Part, Reading
from tests.transfer.conftest import EventViewSet, api_request, call, csv_file

pytestmark = pytest.mark.django_db


def _request(user: Any, path: str = "/parts/import/") -> Any:
    return api_request("post", path, user)


def _run(
    model: Any,
    user: Any,
    rows: list[list[Any]],
    *,
    commit: bool = False,
    match_ids: bool | None = None,
    keep_ids: bool | None = None,
) -> Any:
    job = create_job(model, _request(user), csv_file("rows.csv", rows))
    set_mapping(job, _request(user), job.mapping, match_ids=match_ids, keep_ids=keep_ids)
    job = run_stage(job, PREVIEW, user)
    return run_stage(job, COMMIT, user) if commit else job


def _parts(*numbers: str) -> list[Part]:
    return [Part.objects.create(number=number) for number in numbers]


class TestNaturalKeysFirst:
    def test_a_numeric_natural_key_is_never_read_as_a_primary_key(self, make_user: Any) -> None:
        staff = make_user("staff@example.com", "staff")
        first = Part.objects.create(number="first")
        second = Part.objects.create(number=str(first.pk))  # its number is the first one's id
        rows = [["part", "value"], [first.pk, 10], [second.pk, 20]]
        done = _run(Reading, staff, rows, commit=True)
        assert done.result["created"] == 1 and done.result["errors"] == 1, done.problems
        # The first part's id is the second part's number, so it names the second part.
        assert Reading.objects.get().part == second
        # The second part's id is no part's number: it names nothing.
        assert done.problems[0]["row"] == 3
        assert f"no part with number '{second.pk}'" in done.problems[0]["message"]

    def test_import_lookup_lets_a_column_carry_ids(
        self, make_user: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        staff = make_user("staff@example.com", "staff")
        (part,) = _parts("7")

        class Karni:
            import_lookup = {"part": "id"}

        monkeypatch.setattr(Reading, "Karni", Karni, raising=False)
        done = _run(Reading, staff, [["part", "value"], [part.pk, 10]], commit=True)
        assert done.result["created"] == 1, done.problems
        assert Reading.objects.get().part == part

    def test_a_row_is_matched_by_its_natural_key_not_its_id(self, make_user: Any) -> None:
        staff = make_user("staff@example.com", "staff")
        first, second = _parts("100", "200")
        # The id names the second part, the number the first: the number wins.
        done = _run(
            Part, staff, [["id", "number", "label"], [second.pk, "100", "renamed"]], commit=True
        )
        assert done.result["updated"] == 1, done.problems
        first.refresh_from_db()
        second.refresh_from_db()
        assert first.label == "renamed" and second.label == ""


class TestMatchingIds:
    def test_the_id_column_matches_only_when_asked(self, make_user: Any) -> None:
        staff = make_user("staff@example.com", "staff")
        reading = Reading.objects.create(value=1)
        rows = [["id", "value"], [reading.pk, 5]]
        assert _run(Reading, staff, rows).result["created"] == 1
        job = _run(Reading, staff, rows, match_ids=True)
        assert job.match_ids and job.result["updated"] == 1, job.problems
        done = run_stage(job, COMMIT, staff)
        reading.refresh_from_db()
        assert done.status == "done" and reading.value == 5 and Reading.objects.count() == 1

    def test_a_key_that_matches_nothing_falls_back_to_the_id(self, make_user: Any) -> None:
        staff = make_user("staff@example.com", "staff")
        (part,) = _parts("100")
        rows = [["id", "number"], [part.pk, "101"]]  # renumbered in the spreadsheet
        assert _run(Part, staff, rows, match_ids=True, commit=True).result["updated"] == 1
        part.refresh_from_db()
        assert part.number == "101"

    def test_an_unknown_id_and_a_foreign_one_read_the_same(self, make_user: Any) -> None:
        alice = make_user("alice@example.com", "organizer")
        bob = make_user("bob@example.com", "organizer")
        with current_user(bob):
            bobs = Event.objects.create(title="Bob's", starts_at=timezone.now(), organizer=bob)
        missing = _missing_id(Event)
        request = api_request("post", "/events/import/", alice)
        messages = []
        for pk in (bobs.pk, missing):
            job = create_job(Event, request, csv_file("e.csv", [["id", "title"], [pk, "Mine"]]))
            set_mapping(job, request, job.mapping, match_ids=True)
            job = run_stage(job, PREVIEW, alice)
            assert job.result["errors"] == 1 and job.problems[0]["field"] == "id"
            messages.append(job.problems[0]["message"].replace(repr(str(pk)), "<id>"))
        assert messages[0] == messages[1]
        assert "not found or not in your scope" in messages[0]
        bobs.refresh_from_db()
        assert bobs.title == "Bob's"

    def test_a_natural_key_outside_the_scope_reads_like_a_missing_one(self, make_user: Any) -> None:
        staff = make_user("staff@example.com", "staff")
        importer = Importer(Part, _request(staff))
        assert importer.not_in_scope("number", "100") == (
            "part with number '100': not found or not in your scope, so the row is not imported."
        )


class TestKeepingIds:
    def test_legacy_ids_are_written_and_the_sequence_moves_on(self, make_user: Any) -> None:
        staff = make_user("staff@example.com", "staff")
        rows: list[list[Any]] = [["id", "number"], [500, "A-500"], [501, "A-501"]]
        done = _run(Part, staff, rows, keep_ids=True, commit=True)
        assert done.keep_ids and done.result["created"] == 2, done.problems
        assert set(Part.objects.values_list("pk", flat=True)) == {500, 501}
        fresh = Part.objects.create(number="next")  # would collide with 500 without setval
        assert fresh.pk > 501

    def test_a_preview_never_moves_the_sequence(self, make_user: Any) -> None:
        staff = make_user("staff@example.com", "staff")
        before = Part.objects.create(number="before").pk
        _run(Part, staff, [["id", "number"], [9000, "X"]], keep_ids=True)
        assert not Part.objects.filter(pk=9000).exists()
        assert Part.objects.create(number="after").pk == before + 1

    def test_matching_and_keeping_ids_updates_or_creates_with_the_id(self, make_user: Any) -> None:
        staff = make_user("staff@example.com", "staff")
        reading = Reading.objects.create(value=1)
        rows = [["id", "value"], [reading.pk, 2], [reading.pk + 50, 3]]
        done = _run(Reading, staff, rows, match_ids=True, keep_ids=True, commit=True)
        assert done.result["updated"] == 1 and done.result["created"] == 1, done.problems
        assert Reading.objects.get(pk=reading.pk + 50).value == 3
        assert Reading.objects.create(value=4).pk == reading.pk + 51

    def test_an_id_that_is_not_an_integer_is_refused_on_its_row(self, make_user: Any) -> None:
        staff = make_user("staff@example.com", "staff")
        done = _run(Reading, staff, [["id", "value"], ["x1", 2]], keep_ids=True)
        assert done.result["errors"] == 1 and done.problems[0]["field"] == "id"

    def test_only_a_role_that_may_create_anywhere_keeps_ids(
        self, make_user: Any, venues: Any
    ) -> None:
        manager = make_user("manager@example.com", "venue_manager")
        manager.venue = venues["arena"]
        request = api_request("post", "/events/import/", manager)
        job = create_job(Event, request, csv_file("e.csv", [["id", "title"], [1, "Gig"]]))
        with pytest.raises(KarniValueError, match="Keeping ids needs a role") as refused:
            set_mapping(job, request, job.mapping, keep_ids=True)
        assert refused.value.code == "E801"
        job.refresh_from_db()
        assert not job.keep_ids


class TestTheApi:
    def test_the_preview_body_sets_the_id_options(self, make_user: Any) -> None:
        staff = make_user("staff@example.com", "staff")
        with current_user(staff):
            event = Event.objects.create(title="Gig", starts_at=timezone.now())
        upload = csv_file("events.csv", [["id", "title"], [event.pk, "Renamed"]])
        created = call(
            EventViewSet,
            {"post": "import_data"},
            api_request("post", "/events/import/", staff, {"file": upload}, format="multipart"),
        )
        job = created.data["id"]
        assert created.data["match_ids"] is False and created.data["keep_ids"] is False

        def preview(body: dict[str, Any]) -> Any:
            return call(
                EventViewSet,
                {"post": "import_preview"},
                api_request("post", f"/events/import/{job}/preview/", staff, body, format="json"),
                job=job,
            )

        plain = preview({"mapping": created.data["mapping"]})
        assert plain.data["result"]["created"] == 0 and plain.data["result"]["errors"] == 1
        matched = preview({"match_ids": True})
        assert matched.status_code == 200, matched.data
        assert matched.data["match_ids"] is True and matched.data["result"]["updated"] == 1
        assert preview({}).data["match_ids"] is True  # kept for the commit
        committed = call(
            EventViewSet,
            {"post": "import_commit"},
            api_request("post", f"/events/import/{job}/commit/", staff, {}, format="json"),
            job=job,
        )
        assert committed.data["status"] == "done"
        event.refresh_from_db()
        assert event.title == "Renamed"


class TestLoading:
    def test_karni_load_writes_legacy_ids_and_moves_the_sequence(self, tmp_path: Path) -> None:
        content = tmp_path / "parts.json"
        content.write_text(
            json.dumps(
                {
                    "testapp.Part": [{"number": "L-1"}],
                    "testapp.Reading": [
                        {"id": 300, "value": 1, "part": "L-1"},
                        {"id": 301, "value": 2},
                    ],
                }
            )
        )
        report = load_content(content)
        assert report.models["testapp.Reading"].created == 2
        assert set(Reading.objects.values_list("pk", flat=True)) == {300, 301}
        assert Reading.objects.get(pk=300).part == Part.objects.get(number="L-1")
        assert Reading.objects.create(value=3).pk == 302
        assert load_content(content).changed is False  # matched by id the second time

    def test_a_dry_run_moves_nothing(self, tmp_path: Path) -> None:
        content = tmp_path / "readings.json"
        content.write_text(json.dumps({"testapp.Reading": [{"id": 8000, "value": 1}]}))
        before = Reading.objects.create(value=0).pk
        load_content(content, dry_run=True)
        assert Reading.objects.create(value=0).pk == before + 1


def test_advance_sequences_is_a_no_op_for_uuid_keys_and_empty_tables() -> None:
    from tests.testapp.models import Stamp

    advance_sequences([Stamp, Reading])  # no rows, no integer key: nothing breaks
    assert Reading.objects.create(value=1).pk >= 1


def _missing_id(model: Any) -> Any:
    from karni.testing.hidden import _missing_value

    return _missing_value(model, "pk")
