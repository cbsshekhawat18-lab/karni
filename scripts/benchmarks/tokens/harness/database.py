"""The run's PostgreSQL database: bm_<run id>, created before the run and dropped after."""

from __future__ import annotations

import re
from typing import Protocol

from . import paths

PREFIX = "bm_"


def database_name(run_id: str) -> str:
    """``bm_`` plus the run id with anything but letters, digits and underscores turned to _."""
    name = PREFIX + re.sub(r"[^a-z0-9_]", "_", run_id.lower())
    return name[:63]


class DatabaseAdmin(Protocol):
    def create(self, name: str) -> None: ...

    def drop(self, name: str) -> None: ...


class Postgres:
    """Creates and drops databases on the test PostgreSQL (127.0.0.1:55432), bm_ names only."""

    def __init__(self) -> None:
        import psycopg

        self._connect = lambda: psycopg.connect(
            host=paths.DATABASE_HOST,
            port=paths.DATABASE_PORT,
            user=paths.DATABASE_USER,
            dbname="postgres",
            autocommit=True,
        )

    @staticmethod
    def _check(name: str) -> None:
        if not re.fullmatch(r"bm_[a-z0-9_]{1,60}", name):
            raise ValueError(f"The benchmark only creates and drops bm_ databases, not {name!r}")

    def create(self, name: str) -> None:
        self._check(name)
        with self._connect() as connection:
            connection.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            connection.execute(f'CREATE DATABASE "{name}"')

    def drop(self, name: str) -> None:
        self._check(name)
        with self._connect() as connection:
            connection.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
