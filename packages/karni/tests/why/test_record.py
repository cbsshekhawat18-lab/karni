"""``karni why <status> <request-id>``: replaying a request record the capture layer wrote.

The fixtures are written in the capture layer's format (version 1), which
this package reads and never writes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from django.test import override_settings

from karni.why import WhyError, explain_record, load_record

pytestmark = pytest.mark.django_db


def _record(root: Path, request_id: str, **fields: Any) -> Path:
    data: dict[str, Any] = {
        "version": 1,
        "request_id": request_id,
        "at": "2026-10-21T10:00:00+00:00",
        "method": "GET",
        "path": "/api/guarded-events/",
        "query": {},
        "headers": {"Authorization": "[redacted]"},
        "body": None,
        "content_type": None,
        "user": None,
        "view": "tests.why.routes.GuardedEvents",
        "resource": "guarded-events",
        "action": "list",
        "view_kwargs": {},
        "status": 200,
        "duration_ms": 3.2,
        "error_code": None,
        "failure_id": None,
    }
    data.update(fields)
    folder = root / ".karni" / "requests"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{request_id}.json"
    path.write_text(json.dumps(data))
    return path


def _user_dict(user: Any) -> dict[str, Any]:
    return {
        "id": str(user.pk),
        "email": user.email,
        "username": None,
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
    }


@pytest.fixture
def root(tmp_path: Path) -> Any:
    with override_settings(BASE_DIR=tmp_path):
        yield tmp_path


def test_a_missing_record_says_so_and_names_both_fixes(root: Path) -> None:
    with pytest.raises(WhyError) as caught:
        load_record("nope")
    message = str(caught.value)
    assert caught.value.code == "E903"
    assert str(root / ".karni" / "requests" / "nope.json") in message
    assert "DEBUG" in message and "karni why <resource>/<id> --as <user>" in message


def test_an_unreadable_record_is_e904(root: Path) -> None:
    folder = root / ".karni" / "requests"
    folder.mkdir(parents=True)
    (folder / "bad.json").write_text("{not json")
    with pytest.raises(WhyError, match="E904"):
        load_record("bad")
    _record(root, "old", version=7)
    with pytest.raises(WhyError, match="version is 7"):
        load_record("old")


def test_a_vetoed_delete_replays_with_the_veto_named(root: Path, world: Any) -> None:
    reader = world.users["reader"]
    row = world.rows["bob-draft"]
    _record(
        root,
        "r-403",
        method="DELETE",
        path=f"/api/guarded-events/{row.pk}/",
        action="destroy",
        view_kwargs={"pk": str(row.pk)},
        user=_user_dict(reader),
        status=403,
    )
    verdict = explain_record("r-403", asked=403)
    assert verdict.kind == "record" and verdict.outcome == "veto" and verdict.status == 403
    assert verdict.data["record"]["reproduced"] is True
    text = verdict.text()
    assert text.startswith("record   r-403 at 2026-10-21T10:00:00+00:00: DELETE")
    assert "veto     tests.why.no_reader_deletes" in text
    assert "(the same answer)" in text


def test_a_record_whose_answer_changed_says_so(root: Path, world: Any) -> None:
    alice = world.users["alice"]
    row = world.rows["alice-draft"]
    _record(
        root,
        "r-imp",
        method="DELETE",
        path=f"/api/declared-events/{row.pk}/",
        resource="declared-events",
        action="destroy",
        view_kwargs={"pk": str(row.pk)},
        user=_user_dict(alice),
        status=403,
        error_code="IMP006",
    )
    verdict = explain_record("r-imp", asked=403)
    assert verdict.status == 204 and verdict.data["record"]["reproduced"] is False
    assert "impersonated session" in verdict.notes[0]


def test_an_anonymous_401_is_explained_from_the_record(root: Path, world: Any) -> None:
    row = world.rows["alice-published"]
    _record(
        root,
        "r-401",
        path="/not-an-api/x/",
        resource=None,
        action=None,
        view_kwargs={},
        status=401,
    )
    # Without resource/action the path is resolved against the URLconf; a path no
    # BaseViewSet serves is not an access-layer decision: say so plainly.
    with pytest.raises(WhyError, match="E907"):
        explain_record("r-401")
    _record(
        root,
        "r-401b",
        path=f"/api/granted-events/{row.pk}/",
        resource="granted-events",
        action="retrieve",
        view_kwargs={"pk": str(row.pk)},
        status=401,
    )
    verdict = explain_record("r-401b", asked=401)
    assert verdict.outcome == "unauthenticated"
    assert "sign in" in verdict.fixes[0]


def test_a_record_of_a_deleted_user_cannot_be_replayed(root: Path, world: Any) -> None:
    _record(
        root,
        "r-gone",
        user={"id": "00000000-0000-0000-0000-000000000000", "email": "gone@example.com"},
        status=403,
    )
    with pytest.raises(WhyError, match="gone@example.com") as caught:
        explain_record("r-gone")
    assert caught.value.code == "E902"
