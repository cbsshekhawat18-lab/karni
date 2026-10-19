"""Import: mapping, the dry run, the commit, the permissions and the audit batch."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from karni.audit.models import ChangeBatch, ChangeLog
from karni.exceptions import KarniValueError
from karni.middleware import current_user
from karni.transfer.imports import Importer
from karni.transfer.models import ColumnMapping, ImportJob
from karni.transfer.services import (
    COMMIT,
    PREVIEW,
    create_job,
    job_state,
    run_stage,
    set_mapping,
    start_stage,
)
from tests.testapp.models import Event, Tag
from tests.transfer.conftest import api_request, csv_file, xlsx_file

pytestmark = pytest.mark.django_db

HEADERS = ["title", "starts_at", "venue", "capacity", "is_public"]


def _request(user: Any) -> Any:
    return api_request("post", "/events/import/", user)


def _job(
    user: Any, rows: list[list[Any]], *, name: str = "events.csv", xlsx: bool = False
) -> ImportJob:
    upload = xlsx_file(name, rows) if xlsx else csv_file(name, rows)
    return create_job(Event, _request(user), upload)


def _preview(user: Any, rows: list[list[Any]], **kwargs: Any) -> ImportJob:
    job = _job(user, rows, **kwargs)
    return run_stage(job, PREVIEW, user)


class TestUploadAndMapping:
    def test_the_upload_reads_the_shape_and_suggests_a_mapping(self, make_user: Any) -> None:
        staff = make_user("staff@example.com", "staff")
        job = _job(
            staff,
            [
                ["Title", "Starts at", "venue", "Capacity", "Random"],
                ["Gig", "2026-02-01T10:00:00Z", "Arena", 10, "x"],
            ],
        )
        assert job.status == "uploaded" and job.rows_total == 1 and job.format == "csv"
        assert job.columns == ["Title", "Starts at", "venue", "Capacity", "Random"]
        assert job.mapping == {
            "Title": "title",
            "Starts at": "starts_at",
            "venue": "venue",
            "Capacity": "capacity",
            "Random": "",
        }
        assert job.created_by == staff and job.file.name.endswith(".csv")

    def test_xlsx_uploads_read_the_same_way(self, make_user: Any) -> None:
        staff = make_user("staff@example.com", "staff")
        job = _job(staff, [HEADERS, ["Gig", "2026-02-01T10:00:00Z", "Arena", 10, True]], xlsx=True)
        assert job.format == "xlsx" and job.rows_total == 1 and job.columns == HEADERS

    def test_the_mapping_is_remembered_per_model_per_user(self, make_user: Any) -> None:
        staff = make_user("staff@example.com", "staff")
        job = _job(staff, [["Name", "When"], ["Gig", "2026-02-01T10:00:00Z"]])
        assert job.mapping == {"Name": "", "When": ""}
        set_mapping(job, _request(staff), {"Name": "title", "When": "starts_at"})
        assert ColumnMapping.remembered(staff, Event) == {"Name": "title", "When": "starts_at"}
        again = _job(staff, [["Name", "When", "venue"], ["x", "2026-02-01T10:00:00Z", "Arena"]])
        assert again.mapping == {"Name": "title", "When": "starts_at", "venue": ""}

    def test_a_mapping_to_a_field_the_role_may_not_write_is_refused(self, make_user: Any) -> None:
        staff = make_user("staff@example.com", "staff")
        job = _job(staff, [["t", "s"], ["Gig", "2026-02-01T10:00:00Z"]])
        importer = Importer(Event, _request(staff))
        with pytest.raises(KarniValueError, match="status"):
            importer.validate_mapping(job.columns, {"t": "status"})  # APIMeta.read_only
        with pytest.raises(KarniValueError, match="does not exist"):
            importer.validate_mapping(job.columns, {"t": "nope"})
        with pytest.raises(KarniValueError, match="both map"):
            importer.validate_mapping(job.columns, {"t": "title", "s": "title"})
        with pytest.raises(KarniValueError, match="at least one"):
            importer.validate_mapping(job.columns, {"t": "", "s": ""})

    def test_an_empty_or_oversized_file_is_refused(self, make_user: Any, settings: Any) -> None:
        staff = make_user("staff@example.com", "staff")
        with pytest.raises(KarniValueError, match="E801"):
            create_job(Event, _request(staff), csv_file("empty.csv", []))
        settings.KARNI_IMPORT_MAX_ROWS = 1
        with pytest.raises(KarniValueError, match="E803"):
            _job(
                staff,
                [
                    HEADERS,
                    ["a", "2026-02-01T10:00:00Z", "", "", ""],
                    ["b", "2026-02-01T10:00:00Z", "", "", ""],
                ],
            )
        from django.core.files.uploadedfile import SimpleUploadedFile

        with pytest.raises(KarniValueError, match="E802"):
            upload = SimpleUploadedFile("notes.txt", b"a", content_type="application/octet-stream")
            create_job(Event, _request(staff), upload)


class TestDryRunAndCommit:
    def test_the_preview_counts_without_writing_and_the_commit_writes(
        self, make_user: Any, venues: Any, monkeypatch: Any
    ) -> None:
        monkeypatch.setattr(Event.Karni, "import_key", "title", raising=False)
        staff = make_user("staff@example.com", "staff")
        with current_user(staff):
            existing = Event.objects.create(
                title="Gig", starts_at=timezone.now(), venue=venues["arena"], capacity=5
            )
        rows: list[list[Any]] = [
            HEADERS,
            ["Gig", "2026-02-01T10:00:00Z", "Arena", 50, "true"],  # update (capacity 5 → 50)
            ["New show", "2026-03-01T10:00:00Z", "Hall", "", "false"],  # create
            ["", "2026-03-01T10:00:00Z", "Hall", "", ""],  # error: title required
            ["Lost", "2026-03-01T10:00:00Z", "Nowhere", "", ""],  # error: venue unknown
        ]
        job = _preview(staff, rows)
        assert job.status == "previewed"
        assert job.result == {
            "rows_total": 4,
            "created": 1,
            "updated": 1,
            "unchanged": 0,
            "errors": 2,
            "skipped": 2,
        }
        assert [(p["row"], p["field"]) for p in job.problems] == [(4, "title"), (5, "venue")]
        assert "no venue with name or id 'Nowhere'" in job.problems[1]["message"]
        assert Event.objects.count() == 1  # the dry run wrote nothing
        existing.refresh_from_db()
        assert existing.capacity == 5
        assert ChangeBatch.objects.count() == 0

        done = run_stage(job, COMMIT, staff)
        assert done.status == "done" and done.result == job.result and done.batch_id is not None
        existing.refresh_from_db()
        assert existing.capacity == 50
        created = Event.objects.get(title="New show")
        assert created.venue == venues["hall"] and created.is_public is False
        assert created.created_by == staff
        batch = ChangeBatch.objects.get(pk=done.batch_id)
        assert batch.kind == "import" and batch.actor == staff and batch.label == "events.csv"
        assert batch.meta["job"] == str(job.pk) and batch.meta["model"] == "testapp.Event"

    def test_a_commit_needs_a_preview_first(self, make_user: Any) -> None:
        staff = make_user("staff@example.com", "staff")
        job = _job(staff, [HEADERS, ["Gig", "2026-02-01T10:00:00Z", "", "", ""]])
        with pytest.raises(KarniValueError, match="Preview first"):
            start_stage(job, _request(staff), COMMIT)
        set_mapping(job, _request(staff), job.mapping)
        start_stage(job, _request(staff), PREVIEW)
        job.refresh_from_db()
        assert job.status == "previewed"
        # Changing the mapping after the preview sends the job back to the start.
        set_mapping(job, _request(staff), {**job.mapping, "capacity": ""})
        assert job.status == "uploaded"

    def test_unchanged_rows_are_skipped_and_the_key_is_configurable(
        self, make_user: Any, venues: Any
    ) -> None:
        staff = make_user("staff@example.com", "staff")
        with current_user(staff):
            Event.objects.create(
                title="Gig", starts_at="2026-02-01T10:00:00Z", venue=venues["arena"]
            )
        # Venue has a natural key (name); Event has none, so the row's id is the key.
        gig = Event.objects.get(title="Gig")
        job = _preview(
            staff,
            [
                ["id", "title", "venue"],
                [str(gig.pk), "Gig", "Arena"],
                [str(gig.pk), "Gig renamed", "Arena"],
            ],
        )
        assert job.result["updated"] == 1 and job.result["unchanged"] == 1

    def test_tags_import_by_natural_key_split_on_pipes(self, make_user: Any) -> None:
        staff = make_user("staff@example.com", "staff")
        Tag.objects.create(name="music")
        Tag.objects.create(name="late")
        job = _preview(
            staff, [["title", "starts_at", "tags"], ["Gig", "2026-02-01T10:00:00Z", "music|late"]]
        )
        assert job.result["created"] == 1 and job.problems == []
        done = run_stage(job, COMMIT, staff)
        assert set(Event.objects.get(title="Gig").tags.values_list("name", flat=True)) == {
            "music",
            "late",
        }
        assert done.status == "done"

    def test_choices_and_model_clean_are_validated(self, make_user: Any) -> None:
        from tests.testapp.models import Slot

        staff = make_user("staff@example.com", "staff")
        request = api_request("post", "/slots/import/", staff)
        upload = csv_file(
            "slots.csv",
            [["starts_at", "ends_at"], ["2026-02-01T10:00:00Z", "2026-02-01T09:00:00Z"]],
        )
        job = run_stage(create_job(Slot, request, upload), PREVIEW, staff)
        assert job.result["errors"] == 1 and job.problems, job.result
        assert Slot.objects.count() == 0


class TestPermissions:
    def test_creating_needs_add_and_updating_needs_change(
        self, make_user: Any, venues: Any
    ) -> None:
        reader = make_user("reader@example.com", "reader")
        staff = make_user("staff@example.com", "staff")
        with current_user(staff):
            Event.objects.create(title="Gig", starts_at=timezone.now(), venue=venues["arena"])
        importer = Importer(Event, _request(reader))
        assert not importer.may_create() and not importer.may_update()
        job = _preview(reader, [HEADERS, ["New", "2026-02-01T10:00:00Z", "Arena", "", ""]])
        assert job.result["errors"] == 1 and "may not add" in job.problems[0]["message"]

    def test_rows_of_another_scope_are_not_updated_and_not_created(
        self, make_user: Any, venues: Any
    ) -> None:
        alice = make_user("alice@example.com", "organizer")
        bob = make_user("bob@example.com", "organizer")
        with current_user(bob):
            bobs = Event.objects.create(title="Bob's", starts_at=timezone.now(), organizer=bob)
        job = _preview(alice, [["id", "title"], [str(bobs.pk), "Hijacked"]])
        assert job.result["errors"] == 1 and "not in your scope" in job.problems[0]["message"]
        bobs.refresh_from_db()
        assert bobs.title == "Bob's"
        # A venue manager may add events only at their venue.
        manager = make_user("manager@example.com", "venue_manager")
        manager.venue = venues["arena"]  # what `related:venue` compares against
        job = _preview(
            manager,
            [
                ["title", "starts_at", "venue"],
                ["Home", "2026-02-01T10:00:00Z", "Arena"],
                ["Away", "2026-02-01T10:00:00Z", "Hall"],
            ],
        )
        assert job.result["created"] == 1 and job.result["errors"] == 1
        assert "outside your scope" in job.problems[0]["message"] and job.problems[0]["row"] == 3

    def test_owner_fields_are_stamped_not_imported(self, make_user: Any) -> None:
        alice = make_user("alice@example.com", "organizer")
        importer = Importer(Event, _request(alice))
        assert "organizer" not in {spec.name for spec in importer.importable()}
        job = (
            run_stage(
                _job(alice, [["title", "starts_at"], ["Mine", "2026-02-01T10:00:00Z"]]),
                COMMIT,
                alice,
            )
            if False
            else None
        )
        preview = _preview(alice, [["title", "starts_at"], ["Mine", "2026-02-01T10:00:00Z"]])
        done = run_stage(preview, COMMIT, alice)
        assert done.status == "done" and Event.objects.get(title="Mine").organizer == alice
        assert job is None

    def test_a_field_the_role_may_not_write_is_not_importable(self, make_user: Any) -> None:
        from tests.testapp.models import Customer

        member = make_user("member@example.com", "user")
        importer = Importer(Customer, api_request("post", "/", member))
        names = {spec.name for spec in importer.importable()}
        assert "name" in names and "phone" not in names and "salary" not in names


class TestHooksAndState:
    def test_transform_and_after_import_hooks(self, make_user: Any, monkeypatch: Any) -> None:
        staff = make_user("staff@example.com", "staff")
        seen: list[Any] = []

        def transform(row: dict[str, Any]) -> dict[str, Any]:
            return {**row, "title": row["title"].upper()}

        monkeypatch.setattr(Event.Karni, "import_transform", staticmethod(transform), raising=False)
        monkeypatch.setattr(Event.Karni, "after_import", staticmethod(seen.append), raising=False)
        job = _preview(staff, [["title", "starts_at"], ["quiet", "2026-02-01T10:00:00Z"]])
        assert job.result["created"] == 1 and seen == []  # the dry run never fires after_import
        run_stage(job, COMMIT, staff)
        assert Event.objects.filter(title="QUIET").exists() and len(seen) == 1
        assert seen[0].created == 1

    def test_job_state_and_the_audit_entries_link_to_the_batch(self, make_user: Any) -> None:
        from tests.testapp.models import Price

        staff = make_user("staff@example.com", "staff")
        request = api_request("post", "/prices/import/", staff)
        upload = csv_file(
            "prices.csv", [["amount", "currency"], ["10.00", "EUR"], ["20.00", "USD"]]
        )
        job = run_stage(create_job(Price, request, upload), PREVIEW, staff)
        job = run_stage(job, COMMIT, staff)
        state = job_state(job, request)
        assert state["status"] == "done" and state["result"]["created"] == 2
        assert state["batch"] == job.batch_id and state["async"] is False
        names = [spec["name"] for spec in state["fields"]]
        assert names[0] == "id" and "amount" in names  # the key first, then the writable fields
        entries = ChangeLog.objects.filter(batch_id=job.batch_id)
        assert entries.count() == 2
        assert all(e.content_type == ContentType.objects.get_for_model(Price) for e in entries)
        assert all(e.actor == staff for e in entries)

    def test_large_files_run_in_celery_with_progress(
        self, make_user: Any, settings: Any, monkeypatch: Any
    ) -> None:
        from celery import current_app

        monkeypatch.setattr(current_app.conf, "task_always_eager", True)
        monkeypatch.setattr(current_app.conf, "task_eager_propagates", True)
        settings.KARNI_IMPORT_INLINE_ROWS = 1
        staff = make_user("staff@example.com", "staff")
        job = _job(
            staff,
            [
                HEADERS,
                ["a", "2026-02-01T10:00:00Z", "", "", ""],
                ["b", "2026-02-01T10:00:00Z", "", "", ""],
            ],
        )
        set_mapping(job, _request(staff), job.mapping)
        returned = start_stage(job, _request(staff), PREVIEW)
        assert job_state(returned)["async"] is True
        job.refresh_from_db()
        assert job.status == "previewed" and job.rows_done == 2  # eager: ran at once
        assert Event.objects.count() == 0
        start_stage(job, _request(staff), COMMIT)
        job.refresh_from_db()
        assert job.status == "done" and Event.objects.count() == 2
