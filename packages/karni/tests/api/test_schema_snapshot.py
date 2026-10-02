"""Checked-in OpenAPI snapshot of the testapp schema (api contract B14).

The snapshot is the fixture @karni/ui's schema-parsing tests run against, so
drift between the generated schema and the committed file must fail loudly
with a regenerate hint — silent drift would un-test the frontend parser.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from drf_spectacular.generators import SchemaGenerator

FIXTURE = Path(__file__).parent / "fixtures" / "schema.testapp.json"


def _generated_schema() -> dict:
    schema = SchemaGenerator().get_schema(request=None, public=True)
    # json round-trip normalizes OrderedDicts/enums for a stable comparison
    return json.loads(json.dumps(schema, default=str))


@pytest.mark.django_db
def test_schema_snapshot_is_current() -> None:
    generated = _generated_schema()
    if not FIXTURE.exists():
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(generated, indent=1, sort_keys=True) + "\n")
        pytest.fail(
            f"Snapshot {FIXTURE} did not exist — it has been written now. "
            "Commit it (and copy it to packages/karni-ui/tests/fixtures/) and re-run."
        )
    committed = json.loads(FIXTURE.read_text())
    assert generated == committed, (
        "Generated schema drifted from the committed snapshot. If the change is "
        f"intentional, delete {FIXTURE}, re-run this test to regenerate, and copy "
        "the new file to packages/karni-ui/tests/fixtures/."
    )
