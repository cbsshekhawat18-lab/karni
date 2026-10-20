"""CI-only settings overlay: run packages/karni's test suite against PostgreSQL.

``packages/karni/tests/settings.py`` pins sqlite in-memory and does not read
``DATABASE_URL``, so the Postgres CI job layers this module on top instead:

    cd packages/karni
    PYTHONPATH=../../.github/ci DATABASE_URL=postgres://... \\
        python -m pytest --ds=karni_postgres_settings --no-migrations

``--no-migrations`` is required: ``tests.testapp`` is an unmigrated app with a
ForeignKey to the (migrated) user model, which Django only tolerates on
sqlite. The test database also needs the ``pg_trgm`` extension (the Postgres
search provider calls ``similarity()``); CI installs it into ``template1``,
locally point ``KARNI_TEST_DB_TEMPLATE`` at a database that has it. The
OpenAPI snapshot leaves out the backend-derived integer bounds
(``karni.testing.schema.normalise_schema``), so it runs here too.

Remove this file once tests/settings.py honours ``DATABASE_URL`` itself.
"""

from __future__ import annotations

import os
from pathlib import Path

import environ
from tests.settings import *  # noqa: F403

_db = environ.Env.db_url_config(
    os.environ.get("DATABASE_URL", "postgres://postgres:postgres@localhost:5432/karni")
)
if template := os.environ.get("KARNI_TEST_DB_TEMPLATE"):
    _db["TEST"] = {"TEMPLATE": template}

DATABASES = {"default": _db}

# The project root karni infers is the parent of the settings package — for
# this overlay that is .github/, where no test app lives (the seeding and
# architecture tests then find no project models). Pin it to packages/karni,
# what tests.settings gives on sqlite.
BASE_DIR = Path(__file__).resolve().parents[2] / "packages" / "karni"
