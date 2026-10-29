"""Tables for external models in a test database (experimental).

An external model (``class Karni: external = True``, ``Meta.managed =
False``) reads a table or view another system owns, so neither migrations
nor ``--no-migrations`` create it in a test database. Karni's pytest plugin
calls :func:`create_external_tables` once each test database is migrated:
every external model routed to that database whose table or view is missing
gets a table built from its fields, and on PostgreSQL the schema a
``'schema"."table'`` name points at is created first. A table or view that
exists already (a view the project's own migration creates) is left alone.

Off for a run: ``pytest --karni-external-tables=off``, or
``karni_external_tables = off`` in the pytest ini file. Then call
:func:`create_external_tables` yourself, for example in a session fixture,
with the models you want.

Rows a ``transaction=True`` test writes to such a table stay until the
session ends: Django's flush empties only the tables it manages.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable
from typing import Any

from django.db import DEFAULT_DB_ALIAS, connections
from django.db.models import Model

from karni.db import database_for, external_models, split_table

__all__ = ["create_external_tables"]

#: ``(alias, database name)`` pairs already given their tables this process.
_DONE: set[tuple[str, str]] = set()


def create_external_tables(
    using: str = DEFAULT_DB_ALIAS, models: Iterable[type[Model]] | None = None
) -> list[str]:
    """Experimental. Create the missing table of each external model routed to ``using``.

    ``models`` narrows the models (default: every external model whose
    ``Karni.database`` is ``using``, or which declares none when ``using`` is
    the default database). Returns the ``db_table`` of each table created.
    A schema-qualified table on a database other than PostgreSQL is skipped
    with a ``UserWarning``. Call it outside a transaction: SQLite cannot
    create tables inside one.
    """
    from karni.db.introspection import relation_exists

    connection = connections[using]
    chosen = list(models) if models is not None else _routed_to(using)
    missing: list[type[Model]] = []
    for model in chosen:
        db_table = model._meta.db_table
        schema, _table = split_table(db_table)
        if schema is not None and connection.vendor != "postgresql":
            warnings.warn(
                f"{model._meta.label}: no table is created for {db_table!r} on "
                f"{connection.vendor}, which has no schema {schema!r}. Run the tests that use "
                "it on PostgreSQL.",
                UserWarning,
                stacklevel=2,
            )
            continue
        if not relation_exists(connection, db_table):
            missing.append(model)
    if not missing:
        return []
    schemas = sorted({schema for m in missing if (schema := split_table(m._meta.db_table)[0])})
    with connection.schema_editor() as editor:
        for schema in schemas:
            editor.execute(f"CREATE SCHEMA IF NOT EXISTS {connection.ops.quote_name(schema)}")
        for model in missing:
            editor.create_model(model)
    return [model._meta.db_table for model in missing]


def _routed_to(using: str) -> list[type[Model]]:
    return [
        model for model in external_models() if (database_for(model) or DEFAULT_DB_ALIAS) == using
    ]


def _last_app_with_models() -> Any:
    from django.apps import apps

    configs = [config for config in apps.get_app_configs() if config.models_module is not None]
    return configs[-1] if configs else None


def after_migrate(sender: Any, using: str = DEFAULT_DB_ALIAS, **kwargs: Any) -> None:
    """``post_migrate`` receiver of the pytest plugin: the tables, once per migrated database.

    Django sends ``post_migrate`` once per app, in app order, so the tables are
    created after the last app's, when every managed table they may point at
    exists.
    """
    if sender is not _last_app_with_models():
        return
    connection = connections[using]
    key = (using, str(connection.settings_dict.get("NAME")))
    if key in _DONE:
        return
    create_external_tables(using)
    _DONE.add(key)
