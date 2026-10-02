"""Unit tests for the generator building blocks: naming, field DSL, import merging, rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

from karni_cli.generators.core import FIRST_PARTY, STDLIB, THIRD_PARTY, Workspace
from karni_cli.generators.fields import FieldSpec, RelationTarget, parse_field, render_model_body
from karni_cli.generators.naming import default_route, kebab, pascal, pluralize, snake
from karni_cli.generators.pysource import (
    Import,
    append,
    call,
    ensure_imports,
    replace_or_append,
    tuple_literal,
)
from karni_cli.project import CliError


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    (tmp_path / "events").mkdir()
    (tmp_path / "events" / "models.py").write_text("")
    return Workspace(tmp_path)


# --- naming (mirrors karni.api.routers) ------------------------------------------------


@pytest.mark.parametrize(
    ("model", "route"),
    [
        ("Event", "events"),
        ("Company", "companies"),
        ("Box", "boxes"),
        ("Day", "days"),
        ("APIKey", "api-keys"),
        ("EventType", "event-types"),
        ("Match", "matches"),
    ],
)
def test_default_route_matches_the_auto_router(model: str, route: str) -> None:
    assert default_route(model) == route


def test_case_conversions() -> None:
    assert pascal("event_type") == "EventType"
    assert pascal("event-type") == "EventType"
    assert pascal("EventType") == "EventType"
    assert snake("EventType") == "event_type"
    assert snake("send-digest") == "send_digest"
    assert kebab("HTTPServer") == "http-server"
    assert pluralize("bus") == "buses"


# --- field DSL ------------------------------------------------------------------------


def _body(ws: Workspace, *tokens: str, targets: dict[str, RelationTarget] | None = None) -> str:
    specs = [parse_field(t) for t in tokens]
    rendered = render_model_body(
        specs, model="Event", app_label="events", resolve=targets or {}, line_length=88
    )
    return "\n".join([*rendered.inner, *rendered.lines])


def test_field_types_render(ws: Workspace) -> None:
    body = _body(
        ws,
        "title:str:200",
        "name:str",
        "notes:text?",
        "count:int",
        "price:decimal:8:2?",
        "done:bool",
        "meta:json",
        "ref:uuid",
        "doc:file?",
        "status:choice:draft|in-review",
    )
    assert "title = models.CharField(max_length=200)" in body
    assert "name = models.CharField(max_length=255)" in body
    assert "notes = models.TextField(blank=True)" in body  # strings: blank, never null
    assert "price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)" in (
        body
    )
    assert "done = models.BooleanField(default=False)" in body
    assert "meta = models.JSONField(default=dict)" in body
    assert "ref = models.UUIDField(default=uuid.uuid4)" in body
    assert 'doc = models.FileField(upload_to="events/event/", blank=True)' in body
    assert "class Status(models.TextChoices):" in body
    assert 'IN_REVIEW = "in-review"' in body
    assert "default=Status.DRAFT" in body


def test_relations_render(ws: Workspace) -> None:
    user = RelationTarget("settings.AUTH_USER_MODEL", True, "user")
    body = _body(
        ws,
        "owner:fk:User",
        "editor:fk:User?",
        targets={"owner": user, "editor": user},
    )
    assert "owner = models.ForeignKey(" in body
    assert "on_delete=models.SET_NULL" in body
    # Two relations to the same target get distinct reverse names.
    assert 'related_name="event_owner_set"' in body
    assert 'related_name="event_editor_set"' in body


@pytest.mark.parametrize(
    ("token", "message"),
    [
        ("title", "expected name:type"),
        ("title:strng", "unknown type"),
        ("created_at:datetime", "reserved"),
        ("Title:str", "snake_case"),
        ("_x:str", "may not start with _"),
    ],
)
def test_field_dsl_errors(token: str, message: str) -> None:
    with pytest.raises(CliError, match=message):
        parse_field(token)


def test_field_optional_marker() -> None:
    assert parse_field("venue:fk:Venue?") == FieldSpec("venue", "fk", ("Venue",), True)


# --- imports and layout -------------------------------------------------------------------


def test_import_sections(ws: Workspace) -> None:
    assert ws.import_section("uuid") == STDLIB
    assert ws.import_section("django.db") == THIRD_PARTY
    assert ws.import_section("events.models") == FIRST_PARTY
    # ruff resolves the full module path: a missing submodule is third-party.
    assert ws.import_section("events.tasks") == THIRD_PARTY


def test_ensure_imports_renders_sorted_sections(ws: Workspace) -> None:
    text = '"""Doc."""\n\n\nclass A:\n    pass\n'
    out = ensure_imports(
        ws,
        "x.py",
        text,
        [
            Import("karni.models", "BaseModel"),
            Import("uuid"),
            Import("events.models", "Event"),
            Import("django.db", "models"),
            Import("typing", "TYPE_CHECKING"),
            Import("typing", "Any"),
        ],
    )
    assert out == (
        '"""Doc."""\n\n'
        "import uuid\n"
        "from typing import TYPE_CHECKING, Any\n\n"
        "from django.db import models\n"
        "from karni.models import BaseModel\n\n"
        "from events.models import Event\n\n\n"
        "class A:\n    pass\n"
    )


def test_ensure_imports_merges_into_the_existing_block(ws: Workspace) -> None:
    text = "from django.db import models\n\nX = models\n"
    out = ensure_imports(ws, "x.py", text, [Import("django.db", "connection")])
    assert out.startswith("from django.db import connection, models\n\nX = models\n")
    # Already present: unchanged.
    assert ensure_imports(ws, "x.py", out, [Import("django.db", "models")]) == out


def test_ensure_imports_wraps_long_lines(ws: Workspace) -> None:
    names = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel", "India"]
    out = ensure_imports(ws, "x.py", "", [Import("some.long.module.path", n) for n in names])
    assert out.startswith("from some.long.module.path import (\n    Alpha,\n")
    assert out.rstrip().endswith("India,\n)")


def test_commented_import_block_is_never_rerendered(ws: Workspace) -> None:
    text = "import os  # keep me\nimport sys\n\nprint(os, sys)\n"
    out = ensure_imports(ws, "x.py", text, [Import("json")])
    assert out.startswith("import os  # keep me\nimport sys\nimport json\n")


def test_append_spacing() -> None:
    assert append("import os\n", "x = 1") == "import os\n\nx = 1\n"
    assert append("import os\n", "def f() -> None:\n    pass") == (
        "import os\n\n\ndef f() -> None:\n    pass\n"
    )
    assert append("", "x = 1") == "x = 1\n"


def test_replace_or_append_refuses_then_replaces(tmp_path: Path) -> None:
    text = "# lead comment\ndef f() -> None:\n    pass\n    # trailing body comment\n\n\nx = 1\n"
    with pytest.raises(CliError, match="--force"):
        replace_or_append(Workspace(tmp_path), "m.py", text, "f", "def f() -> int:\n    return 1")
    out = replace_or_append(
        Workspace(tmp_path, force=True), "m.py", text, "f", "def f() -> int:\n    return 1"
    )
    assert out == "def f() -> int:\n    return 1\n\n\nx = 1\n"


def test_call_and_tuple_layout() -> None:
    assert call("x = f", ["a=1"], "", 88) == "x = f(a=1)"
    args = ["max_length=20", "choices=Status.choices"]
    hugged = call("value = models.CharField", args, "", 50)
    assert hugged == ("value = models.CharField(\n    max_length=20, choices=Status.choices\n)")
    exploded = call("value = models.CharField", args, "", 40)
    assert exploded.splitlines()[1:] == ["    max_length=20,", "    choices=Status.choices,", ")"]
    assert tuple_literal("fields = ", ['"a"'], "", 88) == 'fields = ("a",)'
    long = tuple_literal("fields = ", [f'"{c * 20}"' for c in "abc"], "", 40)
    assert long.splitlines()[1] == f'    "{"a" * 20}",'
