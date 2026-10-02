"""CI-only settings overlay: run packages/karni's test suite against PostgreSQL.

``packages/karni/tests/settings.py`` pins sqlite in-memory and does not read
``DATABASE_URL``, so the Postgres CI job layers this module on top instead:

    cd packages/karni
    PYTHONPATH=../../.github/ci DATABASE_URL=postgres://... \\
        python -m pytest --ds=karni_postgres_settings --no-migrations \\
        --deselect tests/api/test_schema_snapshot.py::test_schema_snapshot_is_current

``--no-migrations`` is required: ``tests.testapp`` is an unmigrated app with a
ForeignKey to the (migrated) user model, which Django only tolerates on
sqlite. The test database also needs the ``pg_trgm`` extension (the Postgres
search provider calls ``similarity()``); CI installs it into ``template1``,
locally point ``KARNI_TEST_DB_TEMPLATE`` at a database that has it. The
OpenAPI snapshot is sqlite-generated (integer bounds are backend-derived), so
it is deselected on Postgres.

Remove this file once tests/settings.py honours ``DATABASE_URL`` itself.
"""

from __future__ import annotations

import os

import environ
from tests.settings import *  # noqa: F403

_db = environ.Env.db_url_config(
    os.environ.get("DATABASE_URL", "postgres://postgres:postgres@localhost:5432/karni")
)
if template := os.environ.get("KARNI_TEST_DB_TEMPLATE"):
    _db["TEST"] = {"TEMPLATE": template}

DATABASES = {"default": _db}
