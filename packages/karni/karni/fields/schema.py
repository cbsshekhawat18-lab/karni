"""``karni schema``: every column, constraint and index of a model, and why it exists.

:func:`describe` reads a model the way the database will see it: each
column's type and column-level CHECK, every constraint and index (Django's
own, ``Meta``'s, and what Karni fields added), each with the declaration that
caused it. When the table exists it also asks the database
(``introspection.get_constraints``) and marks each object ``present``,
``missing`` (run ``migrate``) or ``skipped`` (a PostgreSQL-only index on
another database), and lists objects the database has that no declaration
explains. ``usage`` lists the columns routed viewsets search, filter or
order by, with the index that serves each (``karni.W967`` otherwise).

Override / escape hatch: :func:`describe` and :func:`describe_all` are
importable for custom reports; ``manage.py karni_schema --json`` prints the
same data for agents.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from django.db import connections, models

__all__ = ["Column", "DbObject", "ModelSchema", "UsageRow", "describe", "describe_all"]


@dataclass
class Column:
    name: str
    column: str
    type: str
    null: bool
    why: str


@dataclass
class DbObject:
    #: ``primary key``, ``unique``, ``check``, ``index`` or ``constraint``.
    kind: str
    name: str
    columns: list[str]
    definition: str
    why: str
    #: ``present``, ``missing``, ``skipped`` or ``unknown`` (no database read).
    status: str = "unknown"


@dataclass
class UsageRow:
    field: str
    kind: str
    declared_by: str
    covered_by: str | None
    fix: str | None


@dataclass
class ModelSchema:
    label: str
    table: str
    vendor: str
    columns: list[Column] = field(default_factory=list)
    objects: list[DbObject] = field(default_factory=list)
    usage: list[UsageRow] = field(default_factory=list)
    #: Database objects no declaration explains (``name: definition``).
    unexplained: list[str] = field(default_factory=list)
    introspected: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _column_why(model: type[models.Model], model_field: Any) -> str:
    from karni.fields.base import KarniField

    if isinstance(model_field, KarniField):
        return model_field.karni_column()
    origin = _origin(model, model_field)
    kind = type(model_field).__name__
    if model_field.primary_key:
        return f"{kind} primary key{origin}"
    if model_field.is_relation:
        target = model_field.related_model.__name__ if model_field.related_model else "?"
        on_delete = getattr(model_field.remote_field.on_delete, "__name__", "?")
        return f"{kind} to {target}, on_delete={on_delete}{origin}"
    return f"{kind}{origin}"


def _origin(model: type[models.Model], model_field: Any) -> str:
    """`` (from TimestampedModel)`` when an abstract base declared the field."""
    for base in reversed(model.__mro__[1:]):
        meta = getattr(base, "_meta", None)
        if (
            meta is not None
            and meta.abstract
            and any(f.name == model_field.name for f in meta.local_fields)
        ):
            return f" (from {base.__name__})"
    return ""


def _column_type(model_field: Any, connection: Any) -> str:
    kind = str(model_field.db_parameters(connection).get("type") or "")
    return f"{kind} (generated)" if getattr(model_field, "generated", False) else kind


def _statement(build: Any) -> str:
    try:
        return " ".join(str(build()).split())
    except Exception as exc:  # noqa: BLE001 - a report never fails on one object
        return f"(cannot render: {exc})"


def _declared(model: type[models.Model], connection: Any) -> list[DbObject]:
    from karni.fields.base import schema_notes
    from karni.fields.indexes import _PostgresOnly

    notes = schema_notes(model)
    editor = connection.schema_editor(collect_sql=True)
    table = model._meta.db_table
    found: list[DbObject] = []
    for model_field in model._meta.local_concrete_fields:
        column = model_field.column
        if model_field.primary_key:
            found.append(
                DbObject(
                    "primary key",
                    f"{table}_pkey",
                    [column],
                    f"PRIMARY KEY ({column})",
                    _column_why(model, model_field),
                )
            )
            continue
        check = model_field.db_check(connection) if hasattr(model_field, "db_check") else None
        if check:
            found.append(
                DbObject(
                    "check",
                    f"{column} check",
                    [column],
                    f"CHECK ({check})",
                    _column_why(model, model_field),
                )
            )
        if model_field.unique:
            found.append(
                DbObject(
                    "unique",
                    f"{column} unique",
                    [column],
                    f"UNIQUE ({column})",
                    f"{type(model_field).__name__}(unique=True)",
                )
            )
        elif model_field.db_index:
            if model_field.is_relation:
                why = (
                    f"ForeignKey {model_field.name}: Django indexes every foreign key "
                    "(db_index=True), so Karni adds none"
                )
            else:
                why = f"{type(model_field).__name__}(db_index=True){_origin(model, model_field)}"
            found.append(DbObject("index", f"{column} index", [column], f"INDEX ({column})", why))
    for constraint in model._meta.constraints:
        note = notes.get(constraint.name)
        found.append(
            DbObject(
                "constraint",
                constraint.name,
                list(getattr(constraint, "fields", ()) or ()),
                _statement(lambda c=constraint: c.create_sql(model, editor)),
                note.why if note else f"Meta.constraints: {type(constraint).__name__} (declared)",
            )
        )
    for index in model._meta.indexes:
        note = notes.get(index.name)
        skipped = isinstance(index, _PostgresOnly) and connection.vendor != "postgresql"
        found.append(
            DbObject(
                "index",
                index.name,
                list(index.fields),
                _statement(lambda i=index: i.create_sql(model, editor)),
                note.why if note else f"Meta.indexes: {type(index).__name__} (declared)",
                "skipped" if skipped else "unknown",
            )
        )
    for together in model._meta.unique_together:
        found.append(
            DbObject(
                "unique",
                f"{'_'.join(together)} unique_together",
                list(together),
                f"UNIQUE ({', '.join(together)})",
                "Meta.unique_together",
            )
        )
    return found


def _match(
    declared: DbObject, actual: dict[str, dict[str, Any]], columns: dict[str, str]
) -> str | None:
    """The database object's name that implements ``declared``, if any."""
    if declared.name in actual:
        return declared.name
    wanted = [columns.get(name, name) for name in declared.columns]
    for name, info in actual.items():
        if _columns(info) != wanted:
            continue
        if declared.kind == "primary key" and info.get("primary_key"):
            return name
        if declared.kind == "check" and info.get("check"):
            return name
        if declared.kind == "unique" and info.get("unique") and not info.get("primary_key"):
            return name
        if (
            declared.kind == "index"
            and info.get("index")
            and not info.get("unique")
            and not name.endswith("_like")
        ):
            return name
    return None


def _columns(info: dict[str, Any]) -> list[str]:
    """Introspected columns, once each (SQLite's CHECK parser repeats a column per mention)."""
    return list(dict.fromkeys(info.get("columns") or []))


def _introspect(schema: ModelSchema, model: type[models.Model], connection: Any) -> None:
    table = model._meta.db_table
    try:
        with connection.cursor() as cursor:
            if table not in connection.introspection.table_names(cursor):
                return
            actual = connection.introspection.get_constraints(cursor, table)
    except Exception:  # noqa: BLE001 - no database: report the declarations only
        return
    schema.introspected = True
    columns = {f.name: f.column for f in model._meta.local_concrete_fields}
    used: set[str] = set()
    for item in schema.objects:
        if item.status == "skipped":
            continue
        name = _match(item, actual, columns)
        item.status = "present" if name else "missing"
        if name:
            used.add(name)
            if item.name.endswith((" check", " unique", " index")) or item.kind == "primary key":
                item.name = name
    declared_columns = {tuple(columns.get(c, c) for c in item.columns) for item in schema.objects}
    for name, info in sorted(actual.items()):
        if name in used or info.get("foreign_key"):
            continue
        cols = _columns(info)
        if name.endswith("_like") and tuple(cols) in declared_columns:
            continue  # Django's varchar_pattern_ops twin of an indexed text column (PostgreSQL)
        kind = "check" if info.get("check") else "unique" if info.get("unique") else "index"
        schema.unexplained.append(
            f"{name}: {kind} on {', '.join(cols) or 'an expression'} (not declared by the "
            "model: RunSQL, or a declaration since removed)"
        )


def describe(
    model: type[models.Model],
    *,
    using: str = "default",
    introspect: bool = True,
    viewsets: list[type[Any]] | None = None,
) -> ModelSchema:
    """The schema report for ``model`` on database ``using`` (see the module docstring)."""
    from karni.fields.usage import covering_index, suggestion, usage_requirements

    connection = connections[using]
    schema = ModelSchema(model._meta.label, model._meta.db_table, connection.vendor)
    for model_field in model._meta.local_concrete_fields:
        schema.columns.append(
            Column(
                model_field.name,
                model_field.column,
                _column_type(model_field, connection),
                bool(model_field.null),
                _column_why(model, model_field),
            )
        )
    schema.objects = _declared(model, connection)
    if introspect:
        _introspect(schema, model, connection)
    for requirement in usage_requirements(viewsets or []):
        if requirement.model is not model:
            continue
        covered = covering_index(model, requirement.field, requirement.kind)
        schema.usage.append(
            UsageRow(
                requirement.field,
                requirement.kind,
                requirement.declared_by,
                covered,
                None if covered else suggestion(requirement),
            )
        )
    return schema


def routed_viewsets() -> list[type[Any]]:
    """Every viewset the API router serves (empty when the router cannot load)."""
    try:
        from karni.api.routers import resolve_router

        registry = getattr(resolve_router(), "registry", ())
        return [viewset for _prefix, viewset, _basename in registry]
    except Exception:  # noqa: BLE001 - a schema report does not need the API
        return []


def describe_all(
    models_: list[type[models.Model]], *, using: str = "default", introspect: bool = True
) -> list[ModelSchema]:
    """:func:`describe` for each model, sharing one router lookup."""
    viewsets = routed_viewsets()
    return [
        describe(model, using=using, introspect=introspect, viewsets=viewsets) for model in models_
    ]
