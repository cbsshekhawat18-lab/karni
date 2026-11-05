"""Checks for external models and ``Karni.database`` (experimental).

Two kinds:

* **System checks** (no database needed), registered by importing this
  module from :mod:`karni.checks`: :func:`check_database_options`
  (``E270``, ``E271``, ``E275``, ``E276``, ``W541``) and
  :func:`check_database_router` (``W542``). They run on every boot.
* **The table comparison** (:func:`check_external_tables`), which connects
  to each database that holds an external model and compares the model with
  its table or view: ``E272`` no table or view, ``E273`` a column missing,
  ``E274`` a type that clearly does not match, ``W540`` a database that does
  not answer. ``karni check`` runs it. It is not a system check, because
  ``migrate`` runs those, and a view the project's own migration creates does
  not exist before that migration.

Override / escape hatch: silence any code with ``SILENCED_SYSTEM_CHECKS``
(the comparison honours it too), or call :func:`check_external_tables` with
the aliases to compare.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Final

from django.apps import apps
from django.conf import settings
from django.core import checks
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.models import Field, Model
from django.utils.module_loading import import_string

from karni.db import database_for, external_models
from karni.errorcodes import get as registry_entry
from karni.exceptions import check_error, check_warning
from karni.meta import karni_option

__all__ = ["check_database_options", "check_database_router", "check_external_tables"]

ROUTER: Final = "karni.db.DatabaseRouter"

#: Django field types by the kind of value their column holds.
_KINDS: Final[dict[str, str]] = {
    **dict.fromkeys(
        (
            "AutoField",
            "BigAutoField",
            "SmallAutoField",
            "IntegerField",
            "BigIntegerField",
            "SmallIntegerField",
            "PositiveIntegerField",
            "PositiveBigIntegerField",
            "PositiveSmallIntegerField",
        ),
        "integer",
    ),
    **dict.fromkeys(("DecimalField", "FloatField"), "decimal"),
    **dict.fromkeys(("BooleanField", "NullBooleanField"), "boolean"),
    **dict.fromkeys(
        (
            "CharField",
            "TextField",
            "SlugField",
            "EmailField",
            "URLField",
            "FilePathField",
            "FileField",
            "ImageField",
            "GenericIPAddressField",
            "IPAddressField",
        ),
        "text",
    ),
    "DateField": "date",
    "DateTimeField": "datetime",
    "TimeField": "time",
    "DurationField": "duration",
    "UUIDField": "uuid",
    "JSONField": "json",
    "BinaryField": "binary",
}

#: Kinds a column of the other kind still holds: SQLite stores booleans as
#: integers and UUIDs and JSON as text, and a number reads as a decimal.
_COMPATIBLE: Final[frozenset[frozenset[str]]] = frozenset(
    {
        frozenset({"integer", "decimal"}),
        frozenset({"integer", "boolean"}),
        frozenset({"text", "uuid"}),
        frozenset({"text", "json"}),
        frozenset({"integer", "duration"}),
    }
)


def _fix(code: str) -> str:
    entry = registry_entry(code)
    return entry.fix if entry is not None else "See the linked page."


def _models(app_configs: Any) -> list[type[Model]]:
    configs = app_configs if app_configs is not None else apps.get_app_configs()
    return [
        model
        for config in configs
        for model in config.get_models()
        if not model._meta.proxy and not model._meta.swapped
    ]


def _option_types(model: type[Model]) -> list[checks.CheckMessage]:
    found: list[checks.CheckMessage] = []
    for name in ("external", "writable"):
        value = karni_option(model, name, False)
        if not isinstance(value, bool):
            found.append(
                check_error(
                    "E275",
                    f"{model.__name__}.Karni.{name} is {value!r}. It must be True or False.",
                    hint=_fix("E275"),
                    obj=model,
                )
            )
    alias = karni_option(model, "database", None)
    if alias is not None and (not isinstance(alias, str) or not alias):
        found.append(
            check_error(
                "E275",
                f"{model.__name__}.Karni.database is {alias!r}. It must name a DATABASES "
                "alias, e.g. database = 'warehouse'.",
                hint=_fix("E275"),
                obj=model,
            )
        )
    return found


def _alias_of(model: type[Model]) -> str:
    return database_for(model) or DEFAULT_DB_ALIAS


def _relations(model: type[Model]) -> list[checks.CheckMessage]:
    found: list[checks.CheckMessage] = []
    for field in [*model._meta.local_fields, *model._meta.local_many_to_many]:
        if not getattr(field, "is_relation", False):
            continue
        target = getattr(field, "related_model", None)
        if isinstance(target, str):  # a lazy reference ("app.Model") not resolved yet
            try:
                target = apps.get_model(target)
            except (LookupError, ValueError):
                continue
        if not isinstance(target, type):
            continue
        if database_for(model) is None and database_for(target) is None:
            continue
        here, there = _alias_of(model), _alias_of(target)
        if here == there:
            continue
        found.append(
            check_error(
                "E276",
                f"{model.__name__}.{field.name} relates {model.__name__} (database {here!r}) "
                f"to {target.__name__} (database {there!r}). Django joins related tables in "
                "one database, and Karni's router refuses relations across databases.",
                hint=_fix("E276"),
                obj=model,
            )
        )
    return found


@checks.register(checks.Tags.models)
def check_database_options(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E270 / E271 / E275 / E276 / W541: ``Karni.external``, ``writable`` and ``database``."""
    messages: list[checks.CheckMessage] = []
    databases = set(getattr(settings, "DATABASES", {}) or {})
    for model in _models(app_configs):
        problems = _option_types(model)
        messages += problems
        if problems:
            continue
        external = bool(karni_option(model, "external", False))
        if external and model._meta.managed:
            messages.append(
                check_error(
                    "E270",
                    f"{model.__name__} declares class Karni: external = True, but Django "
                    "manages its table (Meta.managed is True), so migrate would create or "
                    "alter a table another system owns.",
                    hint=_fix("E270"),
                    obj=model,
                )
            )
        if karni_option(model, "writable", False) and not external:
            messages.append(
                check_warning(
                    "W541",
                    f"{model.__name__} declares class Karni: writable = True but is not "
                    "external, so the declaration does nothing.",
                    hint=_fix("W541"),
                    obj=model,
                )
            )
        alias = database_for(model)
        if alias is not None and alias not in databases:
            known = ", ".join(sorted(databases)) or "none"
            messages.append(
                check_error(
                    "E271",
                    f"{model.__name__}.Karni.database is {alias!r}, which is not an alias of "
                    f"DATABASES (aliases: {known}).",
                    hint=_fix("E271"),
                    obj=model,
                )
            )
        messages += _relations(model)
    return messages


def _routes_with_karni(entry: Any) -> bool:
    from karni.db import DatabaseRouter

    if isinstance(entry, DatabaseRouter):
        return True
    if isinstance(entry, type):
        return issubclass(entry, DatabaseRouter)
    if isinstance(entry, str):
        if entry == ROUTER:
            return True
        try:
            loaded = import_string(entry)
        except ImportError:
            return False
        return isinstance(loaded, type) and issubclass(loaded, DatabaseRouter)
    return False


@checks.register()
def check_database_router(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.W542: a model declares ``Karni.database`` and the router is not installed."""
    routed = sorted({model.__name__ for model in _models(None) if database_for(model) is not None})
    if not routed:
        return []
    routers = list(getattr(settings, "DATABASE_ROUTERS", None) or [])
    if any(_routes_with_karni(entry) for entry in routers):
        return []
    return [
        check_warning(
            "W542",
            f"{', '.join(routed)} declare class Karni: database, but DATABASE_ROUTERS does not "
            f"list {ROUTER}, so Django sends them to the default database.",
            hint=_fix("W542"),
        )
    ]


# the table comparison (karni check)


def _kind(field_type: str | None) -> str | None:
    return _KINDS.get(field_type) if field_type else None


def _model_kind(field: Field[Any, Any]) -> str | None:
    if field.is_relation:
        target = getattr(field, "target_field", None)
        return _kind(target.get_internal_type()) if target is not None else None
    return _kind(field.get_internal_type())


def _same_column(name: str, found: dict[str, Any], vendor: str) -> Any:
    if name in found:
        return found[name]
    if vendor != "postgresql":
        lowered = {key.lower(): value for key, value in found.items()}
        return lowered.get(name.lower())
    return None


def _compare(model: type[Model], alias: str) -> list[checks.CheckMessage]:
    from karni.db.introspection import columns, relation_exists

    connection = connections[alias]
    table = model._meta.db_table
    if not relation_exists(connection, table):
        return [
            check_error(
                "E272",
                f"{model.__name__} is external, but database {alias!r} has no table or view "
                f"{table!r} (Meta.db_table).",
                hint=_fix("E272"),
                obj=model,
            )
        ]
    found = {column.name: column for column in columns(connection, table)}
    messages: list[checks.CheckMessage] = []
    for field in model._meta.concrete_fields:
        column = _same_column(field.column, found, connection.vendor)
        if column is None:
            messages.append(
                check_error(
                    "E273",
                    f"{model.__name__}.{field.name} reads column {field.column!r}, which "
                    f"{table!r} in database {alias!r} does not have (columns: "
                    f"{', '.join(found) or 'none'}).",
                    hint=_fix("E273"),
                    obj=model,
                )
            )
            continue
        wanted, have = _model_kind(field), _kind(column.field_type)
        if wanted is None or have is None or wanted == have:
            continue
        if frozenset({wanted, have}) in _COMPATIBLE:
            continue
        messages.append(
            check_error(
                "E274",
                f"{model.__name__}.{field.name} is a {type(field).__name__} ({wanted}), but "
                f"column {field.column!r} of {table!r} holds {have} values ({column.field_type} "
                f"to Django).",
                hint=_fix("E274"),
                obj=model,
            )
        )
    return messages


def _reachable(alias: str) -> str | None:
    """``None`` when ``alias`` answers, else the first line of the error."""
    connection = connections[alias]
    try:
        with connection.cursor() as cursor:  # a stale connection object does not count
            cursor.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001 - any failure to connect is the warning's reason
        text = str(exc).strip()
        return text.splitlines()[0] if text else type(exc).__name__
    return None


def check_external_tables(
    databases: Iterable[str] | None = None, models: Iterable[type[Model]] | None = None
) -> list[checks.CheckMessage]:
    """Experimental. Compare each external model with its table or view, where the database answers.

    ``databases`` limits the aliases compared (default: every alias that
    holds an external model), and ``models`` the models (default: every
    external model). ``E272`` no table or view, ``E273`` a model column the
    table lacks, ``E274`` a type that clearly does not match, ``W540`` a
    database that does not answer. Codes in ``SILENCED_SYSTEM_CHECKS`` are
    left out.
    """
    wanted = set(databases) if databases is not None else None
    known = set(connections)
    by_alias: dict[str, list[type[Model]]] = {}
    for model in external_models() if models is None else models:
        alias = _alias_of(model)
        if alias not in known or (wanted is not None and alias not in wanted):
            continue  # an unknown alias is E271's
        by_alias.setdefault(alias, []).append(model)
    messages: list[checks.CheckMessage] = []
    for alias, members in sorted(by_alias.items()):
        problem = _reachable(alias)
        if problem is not None:
            names = ", ".join(model.__name__ for model in members)
            messages.append(
                check_warning(
                    "W540",
                    f"Database {alias!r} did not answer ({problem}), so {names} were not "
                    "compared with their tables.",
                    hint=_fix("W540"),
                )
            )
            continue
        for model in members:
            messages += _compare(model, alias)
    silenced = set(getattr(settings, "SILENCED_SYSTEM_CHECKS", None) or [])
    return [message for message in messages if message.id not in silenced]


def external_check_failures(
    databases: Iterable[str] | None = None, models: Iterable[type[Model]] | None = None
) -> tuple[list[str], list[str]]:
    """``(errors, warnings)`` of :func:`check_external_tables`, rendered for ``karni check``."""
    errors: list[str] = []
    warnings: list[str] = []
    for message in check_external_tables(databases, models):
        text = f"{message.id}: {message.msg}"
        label = getattr(getattr(message.obj, "_meta", None), "label", None)
        if label is not None:
            text = f"{label}: {text}"
        if message.hint:
            text += f"\n\tHINT: {message.hint}"
        (errors if message.is_serious() else warnings).append(text)
    return errors, warnings
