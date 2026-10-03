"""karni.testing.schema: the OpenAPI snapshot and the response-contract validator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from karni.testing import assert_schema_snapshot
from karni.testing import schema as schema_mod
from karni.testing.schema import (
    SNAPSHOT_ENV,
    find_operation,
    generate_schema,
    render_changes,
    schema_changes,
    validate,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _no_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv(SNAPSHOT_ENV, raising=False)
    monkeypatch.setattr(schema_mod, "UPDATE_SNAPSHOTS", False)


def test_a_missing_snapshot_is_written_locally_and_then_holds(tmp_path: Path) -> None:
    target = tmp_path / "openapi.snapshot.json"
    with pytest.warns(UserWarning, match="commit it"):
        assert_schema_snapshot(target)
    assert json.loads(target.read_text()) == generate_schema()
    assert_schema_snapshot(target)  # unchanged API: passes silently


def test_ci_never_writes_a_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    with pytest.raises(AssertionError, match="CI never writes snapshots"):
        assert_schema_snapshot(tmp_path / "missing.json")
    assert not (tmp_path / "missing.json").exists()


def test_an_api_break_fails_with_the_changes_listed(tmp_path: Path) -> None:
    target = tmp_path / "openapi.snapshot.json"
    committed = generate_schema()
    path = next(p for p in committed["paths"] if p.endswith("{id}/"))
    committed["paths"][path]["get"]["summary"] = "old summary"
    committed["paths"]["/api/gone/"] = {"get": {}}
    component = committed["components"]["schemas"]["TestappEvent"]
    component["properties"]["capacity"]["type"] = "string"
    del component["properties"]["title"]
    target.write_text(json.dumps(committed))
    with pytest.raises(AssertionError) as caught:
        assert_schema_snapshot(target, hint="extra hint")
    message = str(caught.value)
    assert "differs from" in message and "breaking" in message
    assert '- removed  paths["/api/gone/"]' in message
    assert "~ changed  components.schemas.TestappEvent.properties.capacity.type" in message
    assert "+ added    components.schemas.TestappEvent.properties.title" in message
    assert f"{SNAPSHOT_ENV}=1 karni test" in message and message.endswith("extra hint")
    lines = message.splitlines()
    first_added = next(i for i, line in enumerate(lines) if "+ added" in line)
    first_removed = next(i for i, line in enumerate(lines) if "- removed" in line)
    assert first_removed < first_added  # breaking changes first


def test_update_rewrites_the_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "openapi.snapshot.json"
    target.write_text("{}")
    assert_schema_snapshot(target, update=True)
    assert json.loads(target.read_text()) == generate_schema()
    target.write_text("{}")
    monkeypatch.setenv(SNAPSHOT_ENV, "1")
    assert_schema_snapshot(target)
    assert json.loads(target.read_text()) != {}


def test_changes_are_sorted_breaking_first() -> None:
    changes = schema_changes({"a": 1, "b": [1, 2], "c": {}}, {"a": 2, "b": [2, 3], "d": 1})
    assert [c.kind for c in changes] == ["changed", "removed", "removed", "added", "added"]
    assert render_changes(changes).startswith("3 breaking, 2 additive")


DOCUMENT = {
    "components": {
        "schemas": {
            "Status": {"enum": ["draft", "live"], "type": "string"},
            "NullEnum": {"enum": [None]},
            "Row": {
                "type": "object",
                "required": ["id", "status"],
                "properties": {
                    "id": {"type": "integer"},
                    "status": {"oneOf": [{"$ref": "#/components/schemas/Status"},
                                         {"$ref": "#/components/schemas/NullEnum"}]},
                    "note": {"type": "string", "nullable": True},
                    "meta": {},
                },
            },
        }
    }
}  # fmt: skip
ROW = {"$ref": "#/components/schemas/Row"}


@pytest.mark.parametrize(
    ("instance", "problem"),
    [
        ({"id": 1, "status": "live", "note": None, "meta": {"x": [1]}}, None),
        ({"id": 1, "status": None}, None),
        ({"id": True, "status": "live"}, "$.id: expected integer, got bool"),
        ({"id": 1, "status": "gone"}, "$.status: matches none of the oneOf options"),
        ({"status": "live"}, "$.id: required by the schema but missing"),
        ({"id": 1, "status": "live", "extra": 1}, "$.extra: not declared in the schema"),
        ({"id": 1, "status": "live", "note": 3}, "$.note: expected string, got int"),
    ],
)
def test_validate(instance: dict[str, object], problem: str | None) -> None:
    errors = validate(instance, ROW, DOCUMENT)
    assert (errors == []) if problem is None else any(problem in e for e in errors), errors


def test_find_operation_matches_path_templates() -> None:
    document = {"paths": {"/api/events/{id}/": {"get": {"operationId": "x"}}}}
    assert find_operation(document, "/api/events/5/", "GET") == {"operationId": "x"}
    assert find_operation(document, "/api/events/5/", "DELETE") is None
    assert find_operation(document, "/api/events/", "GET") is None
