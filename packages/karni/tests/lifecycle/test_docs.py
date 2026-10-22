"""docs/lifecycle-and-capacity.md shows the exact SQL the models create: compared line by line."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.apps import apps
from django.db import connection

DOCS = Path(__file__).resolve().parents[4] / "docs" / "lifecycle-and-capacity.md"

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="the page shows PostgreSQL's DDL (CI's Postgres step compares it)",
    ),
]


def _blocks() -> list[tuple[str, list[str]]]:
    text = DOCS.read_text()
    found = re.findall(r"<!-- karni:sql:(\w+) -->\s*```sql\n(.*?)```", text, re.S)
    assert found, "docs/lifecycle-and-capacity.md lost its karni:sql blocks"
    return [
        (model, [line.strip() for line in sql.splitlines() if line.strip()]) for model, sql in found
    ]


def _ddl(model_name: str) -> str:
    model = apps.get_model("lifecycleapp", model_name)
    with connection.schema_editor(collect_sql=True) as editor:
        editor.create_model(model)
    return "\n".join(editor.collected_sql)


@pytest.mark.parametrize(("model", "lines"), _blocks(), ids=[m for m, _ in _blocks()])
def test_every_sql_line_on_the_page_is_what_the_model_creates(model: str, lines: list[str]) -> None:
    pytest.importorskip("psycopg")
    ddl = _ddl(model)
    for line in lines:
        assert line.rstrip(";,") in ddl, f"docs show {line!r}; {model} creates:\n{ddl}"
