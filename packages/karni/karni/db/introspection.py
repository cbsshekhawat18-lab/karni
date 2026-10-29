"""What a database says about one table or view, schema-qualified names included (experimental).

Django's introspection finds a PostgreSQL table only on the search path, so
for ``'reporting"."sales'`` these helpers put the schema on the search path
for the duration of the call and restore it after. Every other backend has no
schemas in Karni's sense: a schema-qualified name there is a table that does
not exist.

:func:`relation_exists` and :func:`columns` back the ``karni check``
comparison (:func:`karni.db.checks.check_external_tables`), and
:func:`inspect_table` backs ``karni make model --external`` through
``manage.py karni_inspect`` (Django's ``inspectdb`` machinery: field types,
``null``, ``max_length``, the primary key).

Override / escape hatch: these are plain functions over a connection. Call
them from your own check, or subclass the ``karni_inspect`` command.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from django.db.backends.base.base import BaseDatabaseWrapper

from karni.db import split_table

__all__ = ["Column", "columns", "inspect_table", "relation_exists", "relation_kind"]


@dataclass(frozen=True)
class Column:
    """Experimental. One column of a table or view: its name and the Django field type it maps to.

    ``field_type`` is ``None`` when the database reports no type Django knows
    (an expression column of a SQLite view, a custom PostgreSQL type).
    """

    name: str
    field_type: str | None
    null: bool


def _is_postgres(connection: BaseDatabaseWrapper) -> bool:
    return connection.vendor == "postgresql"


@contextmanager
def _search_path(
    connection: BaseDatabaseWrapper, cursor: Any, schema: str | None
) -> Iterator[None]:
    """Put ``schema`` alone on PostgreSQL's search path inside the block, then restore it."""
    if schema is None or not _is_postgres(connection):
        yield
        return
    cursor.execute("SELECT current_setting('search_path')")
    before = cursor.fetchone()[0]
    cursor.execute(
        "SELECT set_config('search_path', %s, false)", [connection.ops.quote_name(schema)]
    )
    try:
        yield
    finally:
        cursor.execute("SELECT set_config('search_path', %s, false)", [before])


def relation_exists(connection: BaseDatabaseWrapper, db_table: str) -> bool:
    """Experimental. Whether a table or view ``db_table`` exists (``'schema"."table'`` too)."""
    schema, table = split_table(db_table)
    with connection.cursor() as cursor:
        if _is_postgres(connection):
            cursor.execute("SELECT to_regclass(%s)", [connection.ops.quote_name(db_table)])
            return cursor.fetchone()[0] is not None
        if schema is not None:
            return False
        names = connection.introspection.table_names(cursor, include_views=True)
    return table in names or table.lower() in {name.lower() for name in names}


def relation_kind(connection: BaseDatabaseWrapper, db_table: str) -> str | None:
    """Experimental. ``"table"`` or ``"view"`` for an existing ``db_table``, else ``None``."""
    schema, table = split_table(db_table)
    if schema is not None and not _is_postgres(connection):
        return None
    with connection.cursor() as cursor, _search_path(connection, cursor, schema):
        for info in connection.introspection.get_table_list(cursor):
            if info.name == table:
                return "view" if info.type == "v" else "table"
    return None


def _field_type(connection: BaseDatabaseWrapper, row: Any) -> str | None:
    try:
        return str(connection.introspection.get_field_type(row.type_code, row))
    except KeyError:
        return None


def columns(connection: BaseDatabaseWrapper, db_table: str) -> list[Column]:
    """Experimental. The columns of an existing table or view, in their order."""
    schema, table = split_table(db_table)
    with connection.cursor() as cursor, _search_path(connection, cursor, schema):
        description = connection.introspection.get_table_description(cursor, table)
    return [
        Column(row.name, _field_type(connection, row), bool(row.null_ok)) for row in description
    ]


def inspect_table(connection: BaseDatabaseWrapper, db_table: str) -> dict[str, Any]:
    """Experimental. The model fields Django's ``inspectdb`` derives from ``db_table``, as data.

    ``{"kind", "fields": [{"name", "type", "params", "notes"}], "notes"}``:
    ``type`` is a ``django.db.models`` field class name and ``params`` its
    keyword arguments (``primary_key``, ``max_length``, ``null``, ``blank``,
    ``unique``, ``db_column``, ``max_digits``, ``decimal_places``). A column
    with a foreign key becomes a plain field of the key's type, with a note
    naming the table it points at. A table without a primary key (any view)
    gets its ``id`` column, else its first unique column, else its first
    column as the primary key, with a note.
    """
    from django.core.management.commands.inspectdb import Command as InspectDB

    schema, table = split_table(db_table)
    inspector = InspectDB()
    notes: list[str] = []
    with connection.cursor() as cursor, _search_path(connection, cursor, schema):
        try:
            relations = connection.introspection.get_relations(cursor, table)
        except NotImplementedError:
            relations = {}
        try:
            constraints = connection.introspection.get_constraints(cursor, table)
        except NotImplementedError:
            constraints = {}
        primary = list(connection.introspection.get_primary_key_columns(cursor, table) or [])
        description = connection.introspection.get_table_description(cursor, table)
        kind = "table"
        for info in connection.introspection.get_table_list(cursor):
            if info.name == table and info.type == "v":
                kind = "view"
    unique = [
        found["columns"][0]
        for found in constraints.values()
        if found.get("unique") and len(found.get("columns") or ()) == 1
    ]
    names = [row.name for row in description]
    if len(primary) > 1:
        notes.append(
            f"The primary key spans {', '.join(primary)}. Karni's API and admin need one "
            f"column, so {primary[0]} is the primary key: move primary_key=True to a column "
            "whose values are unique on their own if there is one."
        )
        primary = primary[:1]
    if not primary:
        chosen = next(
            (name for name in names if name == "id"),
            next((name for name in names if name in unique), names[0] if names else None),
        )
        if chosen is not None:
            primary = [chosen]
            notes.append(
                f"The {kind} has no primary key, so {chosen} is the primary key. Django needs "
                f"one column whose values are unique: move primary_key=True if {chosen} is "
                "not that column."
            )
    used: list[str] = []
    fields: list[dict[str, Any]] = []
    for row in description:
        column = row.name
        name, params, field_notes = inspector.normalize_col_name(column, used, False)
        used.append(name)
        params = dict(params)
        field_notes = list(field_notes)
        field_type, type_params, type_notes = inspector.get_field_type(connection, table, row)
        params.update(type_params)
        field_notes.extend(type_notes)
        if field_type == "CharField" and "max_length" not in params:
            field_type = "TextField"
        if column in primary:
            params["primary_key"] = True
        elif column in unique:
            params["unique"] = True
        if column in relations:
            target_column, target_table = relations[column]
            field_notes.append(
                f"A foreign key to {target_table}.{target_column}: make it a ForeignKey("
                "..., on_delete=models.DO_NOTHING, db_constraint=False) once that model exists."
            )
        if row.null_ok and not params.get("primary_key"):
            params["blank"] = True
            params["null"] = True
        params.pop("db_collation", None)
        fields.append({"name": name, "type": field_type, "params": params, "notes": field_notes})
    return {"kind": kind, "fields": fields, "notes": notes}
