"""The API contract: the OpenAPI schema must match tests/openapi.snapshot.json.

The first local run writes the snapshot — commit it. From then on any change
to the API (a removed field, a changed type, a new endpoint) fails here with
the changes listed. Accept an intended change with
`KARNI_UPDATE_SNAPSHOTS=1 karni test` and commit the updated file. CI never
writes a snapshot.
"""

import pytest

from karni.testing import assert_schema_snapshot


@pytest.mark.django_db
def test_the_api_contract_is_unchanged():
    assert_schema_snapshot()
