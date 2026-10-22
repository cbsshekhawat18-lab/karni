"""CI-only settings overlay: run a package's test suite against PostgreSQL.

Every suite that runs here (``packages/karni`` and the three modules in
``modules/``) pins sqlite in-memory in its own ``tests/settings.py`` and does
not read ``DATABASE_URL``, so the Postgres CI job layers this module on top
instead. It imports whichever ``tests.settings`` the working directory
provides, so the same overlay serves every suite:

    cd packages/karni   # or modules/karni-payments, modules/karni-approvals, ...
    PYTHONPATH=../../.github/ci DATABASE_URL=postgres://... \\
        python -m pytest --ds=karni_postgres_settings --no-migrations

``--no-migrations`` is required: ``tests.testapp`` (in packages/karni,
karni-approvals and karni-impersonation) is an unmigrated app with a
ForeignKey to the (migrated) user model, which Django only tolerates on
sqlite. The test database also needs the ``pg_trgm`` extension (the Postgres
search provider calls ``similarity()``); CI installs it into ``template1``,
locally point ``KARNI_TEST_DB_TEMPLATE`` at a database that has it. The
OpenAPI snapshot leaves out the backend-derived integer bounds
(``karni.testing.schema.normalise_schema``), so it runs here too.

Remove this file once every suite's tests/settings.py honours ``DATABASE_URL``
itself.
"""

from __future__ import annotations

import os
from pathlib import Path

import environ
import tests.settings as _suite_settings
from tests.settings import *  # noqa: F403

_db = environ.Env.db_url_config(
    os.environ.get("DATABASE_URL", "postgres://postgres:postgres@localhost:5432/karni")
)
if template := os.environ.get("KARNI_TEST_DB_TEMPLATE"):
    _db["TEST"] = {"TEMPLATE": template}

DATABASES = {"default": _db}

# The project root karni infers is the parent of the settings package — for
# this overlay that is .github/, where no test app lives (the seeding and
# architecture tests then find no project models). Pin it to the suite's own
# root (packages/karni, or the module's directory), what tests.settings gives
# on sqlite.
BASE_DIR = Path(_suite_settings.__file__).resolve().parents[1]
