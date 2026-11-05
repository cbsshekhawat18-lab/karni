"""``manage.py karni_inspect <[schema.]table> [--database <alias>]``: a table's columns as fields.

Experimental. It backs ``karni make model <Name> --external --table
<[schema.]table>``, which runs it in the project's interpreter and writes the
model from what it prints: one line, :data:`MARKER` followed by JSON.

- ``{"status": "ok", "db_table", "database", "vendor", "kind", "fields", "notes"}``:
  ``fields`` as :func:`karni.db.introspection.inspect_table` derives them
  with Django's ``inspectdb`` machinery;
- ``{"status": "unknown-alias", "database", "aliases"}``;
- ``{"status": "unreachable", "database", "error"}``: the database did not answer;
- ``{"status": "missing", "database", "db_table"}``: no such table or view;
- ``{"status": "no-schemas", "database", "vendor", "db_table"}``: a schema on a
  database other than PostgreSQL.

``reporting.sales`` names the table ``sales`` in the PostgreSQL schema
``reporting`` (``db_table = 'reporting"."sales'``).

Override / escape hatch: subclass this command (``describe`` returns the
answer) or call :func:`karni.db.introspection.inspect_table` yourself.
"""

from __future__ import annotations

import json
from typing import Any, Final

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from django.db import DEFAULT_DB_ALIAS, connections

MARKER: Final = "karni-inspect: "


def db_table_for(name: str) -> str:
    """``reporting.sales`` or ``reporting"."sales`` → ``'reporting"."sales'``. A bare name stays."""
    if '"."' in name:
        return name.strip('"')
    schema, dot, table = name.partition(".")
    return f'{schema}"."{table}' if dot and schema and table else name


class Command(BaseCommand):
    help = (
        "Experimental. Print a table's or view's columns as Django model fields, in JSON "
        "(karni make model --external)."
    )
    requires_system_checks: list[Any] = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("table", help="The table or view: name, or schema.name (PostgreSQL).")
        parser.add_argument(
            "--database", default=DEFAULT_DB_ALIAS, help="The DATABASES alias (default: default)."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        answer = self.describe(str(options["table"]), str(options["database"]))
        self.stdout.write(MARKER + json.dumps(answer))

    def describe(self, table: str, alias: str) -> dict[str, Any]:
        """The answer :data:`MARKER` precedes (see the module docstring)."""
        from karni.db import split_table
        from karni.db.introspection import inspect_table, relation_exists

        db_table = db_table_for(table)
        aliases = sorted(getattr(settings, "DATABASES", {}) or {})
        if alias not in aliases:
            return {"status": "unknown-alias", "database": alias, "aliases": aliases}
        connection = connections[alias]
        try:
            connection.ensure_connection()
        except Exception as exc:  # noqa: BLE001 - any failure to connect is the answer
            text = str(exc).strip()
            error = text.splitlines()[0] if text else type(exc).__name__
            return {"status": "unreachable", "database": alias, "error": error}
        schema, _name = split_table(db_table)
        if schema is not None and connection.vendor != "postgresql":
            return {
                "status": "no-schemas",
                "database": alias,
                "vendor": connection.vendor,
                "db_table": db_table,
            }
        if not relation_exists(connection, db_table):
            return {"status": "missing", "database": alias, "db_table": db_table}
        found = inspect_table(connection, db_table)
        return {
            "status": "ok",
            "db_table": db_table,
            "database": alias,
            "vendor": connection.vendor,
            **found,
        }
