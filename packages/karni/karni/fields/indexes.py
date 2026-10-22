"""PostgreSQL index types that stay portable, and the append-only BRIN declaration.

:class:`GinIndex`, :class:`GistIndex` and :class:`BrinIndex` are Django's
``django.contrib.postgres`` indexes with one difference: on another database
(SQLite in tests and local development) creating or dropping them is a
no-op SQL comment instead of a syntax error, so one migration runs
everywhere. ``karni.W964`` says what the other database does without them.
They are what Karni fields contribute (a ``SearchField``'s GIN, an
``ArrayField``'s GIN, a queried ``JSONField``'s GIN) and the hook range
fields use for GiST::

    from karni.fields import GistIndex, contribute_index

    contribute_index(model, GistIndex(fields=["during"]), "DateRangeField: overlap lookups")

``class Karni: append_only = True`` on a model replaces the B-tree index on
its ``auto_now_add`` timestamp columns (``created_at``) with a BRIN index: a
few kilobytes instead of a B-tree the size of the column, for tables that
only grow and are scanned by time range. A list of column names picks the
columns instead. The trade-off: BRIN cannot serve ``ORDER BY created_at
LIMIT n``, so do not declare it on a table listed newest-first.

Override / escape hatch: use ``django.contrib.postgres.indexes`` directly
for PostgreSQL-only migrations, or declare any index in ``Meta.indexes``.
"""

from __future__ import annotations

from typing import Any

from django.contrib.postgres import indexes as pg_indexes
from django.db import models
from django.db.backends.ddl_references import Statement

from karni.fields.base import PUBLIC_PATH, contribute_index
from karni.meta import karni_option

__all__ = ["BrinIndex", "GinIndex", "GistIndex", "append_only_columns", "append_only_indexes"]


class _PostgresOnly:
    """Create/drop on PostgreSQL; a commented no-op statement elsewhere."""

    name: str

    def _skipped(self, schema_editor: Any) -> Statement:
        return Statement(
            "-- karni: %(index)s (%(kind)s) is PostgreSQL-only; not created on %(vendor)s",
            index=self.name,
            kind=type(self).__name__,
            vendor=schema_editor.connection.vendor,
        )

    def create_sql(self, model: Any, schema_editor: Any, using: str = "", **kwargs: Any) -> Any:
        if schema_editor.connection.vendor != "postgresql":
            return self._skipped(schema_editor)
        return super().create_sql(model, schema_editor, using=using, **kwargs)  # type: ignore[misc]

    def remove_sql(self, model: Any, schema_editor: Any, **kwargs: Any) -> Any:
        if schema_editor.connection.vendor != "postgresql":
            return self._skipped(schema_editor)
        return super().remove_sql(model, schema_editor, **kwargs)  # type: ignore[misc]

    def deconstruct(self) -> tuple[str, tuple[Any, ...], dict[str, Any]]:
        _path, args, kwargs = super().deconstruct()  # type: ignore[misc]
        return f"{PUBLIC_PATH}.{type(self).__name__}", args, kwargs


class GinIndex(_PostgresOnly, pg_indexes.GinIndex):
    """GIN (jsonb, arrays, tsvector, trigrams) on PostgreSQL; skipped elsewhere."""


class GistIndex(_PostgresOnly, pg_indexes.GistIndex):
    """GiST (ranges, exclusion) on PostgreSQL; skipped elsewhere."""


class BrinIndex(_PostgresOnly, pg_indexes.BrinIndex):
    """BRIN (large append-only tables) on PostgreSQL; skipped elsewhere."""


def append_only_columns(model: type[models.Model]) -> list[str]:
    """The field names ``Karni.append_only`` asks a BRIN index for (empty when undeclared)."""
    declared = karni_option(model, "append_only", False)
    if not declared:
        return []
    if declared is True:
        return [
            field.name
            for field in model._meta.local_concrete_fields
            if isinstance(field, models.DateTimeField) and getattr(field, "auto_now_add", False)
        ]
    if isinstance(declared, str):
        return [declared]
    return [str(name) for name in declared]


def append_only_indexes(model: type[models.Model]) -> None:
    """Swap the B-tree for a BRIN on each ``Karni.append_only`` column (real models only).

    Unknown names are left to ``karni.E970``.
    """
    names = {field.name: field for field in model._meta.local_concrete_fields}
    for name in append_only_columns(model):
        field: Any = names.get(name)
        if field is None:
            continue
        field.db_index = False
        contribute_index(
            model,
            BrinIndex(fields=[name]),
            f"Karni.append_only: BRIN instead of a B-tree on {name} (time-range scans on a "
            "table that only grows)",
        )
