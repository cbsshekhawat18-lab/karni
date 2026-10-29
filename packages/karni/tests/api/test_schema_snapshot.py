"""Checked-in OpenAPI snapshot of the testapp schema (api contract B14).

The snapshot is the fixture @karni/ui's schema-parsing tests run against, so
drift between the generated schema and the committed file must fail loudly
with a regenerate hint — silent drift would un-test the frontend parser. The
comparison is :func:`karni.testing.assert_schema_snapshot`, the same helper
projects use. There is one snapshot per key type of the test app's models:
``schema.testapp.json`` (UUID keys) and, under ``KARNI_TEST_PK=bigint``,
``schema.testapp.bigint.json`` (integer keys).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from karni.testing import assert_schema_snapshot
from tests.testapp.models import TEST_PK

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / ("schema.testapp.json" if TEST_PK == "uuid" else f"schema.testapp.{TEST_PK}.json")
)


@pytest.mark.django_db
def test_schema_snapshot_is_current() -> None:
    assert_schema_snapshot(
        FIXTURE,
        hint="Then copy the file to packages/karni-ui/tests/fixtures/ (the UI parser tests).",
    )
