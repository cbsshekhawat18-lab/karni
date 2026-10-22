"""The import endpoints on every BaseViewSet, end to end."""

from __future__ import annotations

from typing import Any

import pytest
from drf_spectacular.generators import SchemaGenerator

from tests.testapp.models import Event
from tests.transfer.conftest import EventViewSet, api_request, build_router, call, csv_file

pytestmark = pytest.mark.django_db

HEADERS = ["title", "starts_at", "venue"]


def _post(user: Any, path: str, data: Any, **kwargs: Any) -> Any:
    return api_request(
        "post", path, user, data, format="multipart" if "file" in data else "json", **kwargs
    )


def test_describe_upload_preview_commit(make_user: Any, venues: Any) -> None:
    staff = make_user("staff@example.com", "staff")
    describe = call(
        EventViewSet, {"get": "import_data"}, api_request("get", "/events/import/", staff)
    )
    assert describe.status_code == 200
    assert {f["name"] for f in describe.data["fields"]} >= {"title", "starts_at", "venue", "tags"}
    assert describe.data["mapping"] == {} and describe.data["inline_rows"] == 500
    venue = next(f for f in describe.data["fields"] if f["name"] == "venue")
    assert venue == {
        "name": "venue",
        "label": "Venue",
        "kind": "relation",
        "required": False,
        "readable": True,
        "writable": True,
        "choices": [],
        "target": "testapp.venue",
        "lookup": "name",
        "help": "",
        "key": False,
    }

    upload = csv_file("events.csv", [HEADERS, ["Gig", "2026-02-01T10:00:00Z", "Arena"]])
    created = call(
        EventViewSet, {"post": "import_data"}, _post(staff, "/events/import/", {"file": upload})
    )
    assert created.status_code == 201, created.data
    job = created.data["id"]
    assert created.data["status"] == "uploaded" and created.data["mapping"]["venue"] == "venue"

    previewed = call(
        EventViewSet,
        {"post": "import_preview"},
        _post(staff, f"/events/import/{job}/preview/", {"mapping": created.data["mapping"]}),
        job=job,
    )
    assert previewed.status_code == 200, previewed.data
    assert previewed.data["status"] == "previewed" and previewed.data["result"]["created"] == 1
    assert Event.objects.count() == 0

    state = call(EventViewSet, {"get": "import_job"}, api_request("get", "/", staff), job=job)
    assert state.status_code == 200 and state.data["status"] == "previewed"

    committed = call(
        EventViewSet,
        {"post": "import_commit"},
        _post(staff, f"/events/import/{job}/commit/", {}),
        job=job,
    )
    assert committed.status_code == 200 and committed.data["status"] == "done"
    assert Event.objects.get(title="Gig").venue == venues["arena"]


def test_a_commit_before_the_preview_is_refused(make_user: Any) -> None:
    staff = make_user("staff@example.com", "staff")
    upload = csv_file("events.csv", [HEADERS, ["Gig", "2026-02-01T10:00:00Z", ""]])
    created = call(
        EventViewSet, {"post": "import_data"}, _post(staff, "/events/import/", {"file": upload})
    )
    job = created.data["id"]
    response = call(
        EventViewSet,
        {"post": "import_commit"},
        _post(staff, f"/events/import/{job}/commit/", {}),
        job=job,
    )
    assert response.status_code == 400 and "E801" in str(response.data)


def test_jobs_are_private_and_the_gate_is_add_or_change(make_user: Any) -> None:
    staff = make_user("staff@example.com", "staff")
    reader = make_user("reader@example.com", "reader")
    alice = make_user("alice@example.com", "organizer")
    upload = csv_file("events.csv", [HEADERS, ["Gig", "2026-02-01T10:00:00Z", ""]])
    created = call(
        EventViewSet, {"post": "import_data"}, _post(staff, "/events/import/", {"file": upload})
    )
    job = created.data["id"]
    # Someone else's job is a 404, even for another importer.
    other = call(EventViewSet, {"get": "import_job"}, api_request("get", "/", alice), job=job)
    assert other.status_code == 404
    # A reader holds neither add nor change: the gate refuses before anything runs.
    refused = call(
        EventViewSet,
        {"post": "import_data"},
        _post(
            reader,
            "/events/import/",
            {"file": csv_file("e.csv", [HEADERS, ["x", "2026-02-01T10:00:00Z", ""]])},
        ),
    )
    assert refused.status_code == 403
    assert (
        call(EventViewSet, {"get": "import_data"}, api_request("get", "/", reader)).status_code
        == 403
    )


def test_the_schema_documents_export_and_import(make_user: Any) -> None:
    paths = SchemaGenerator(patterns=build_router().urls).get_schema(request=None, public=True)[
        "paths"
    ]
    assert "/events/export/" in paths and "/events/import/" in paths
    export = paths["/events/export/"]["get"]
    assert [p["name"] for p in export["parameters"] if p["name"] == "format"] == ["format"]
    assert "200" in export["responses"]
    upload = paths["/events/import/"]["post"]
    assert "multipart/form-data" in upload["requestBody"]["content"]
    assert "/events/import/{job}/preview/" in paths and "/events/import/{job}/commit/" in paths
    assert "/events/import/template/" in paths


def test_every_operation_id_is_unique(make_user: Any) -> None:
    """``GET import/`` and ``GET import/{job}/`` used to share an ID (a client got ``_2``)."""
    paths = SchemaGenerator(patterns=build_router().urls).get_schema(request=None, public=True)[
        "paths"
    ]
    ids = [
        op["operationId"] for item in paths.values() for op in item.values() if "operationId" in op
    ]
    assert len(ids) == len(set(ids))
    assert paths["/events/import/{job}/"]["get"]["operationId"] == "events_import_by_job_retrieve"
    assert paths["/events/import/"]["get"]["operationId"] == "events_import_retrieve"
    assert paths["/events/{id}/"]["get"]["operationId"] == "events_retrieve"  # detail unchanged
