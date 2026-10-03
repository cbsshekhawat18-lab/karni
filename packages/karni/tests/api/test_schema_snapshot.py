"""Checked-in OpenAPI snapshot of the testapp schema (api contract B14).

The snapshot is the fixture @karni/ui's schema-parsing tests run against, so
drift between the generated schema and the committed file must fail loudly
with a regenerate hint — silent drift would un-test the frontend parser. The
comparison is :func:`karni.testing.assert_schema_snapshot`, the same helper
projects use.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from karni.testing import assert_schema_snapshot

FIXTURE = Path(__file__).parent / "fixtures" / "schema.testapp.json"


@pytest.mark.django_db
def test_schema_snapshot_is_current() -> None:
    assert_schema_snapshot(
        FIXTURE,
        hint="Then copy the file to packages/karni-ui/tests/fixtures/ (the UI parser tests).",
    )
