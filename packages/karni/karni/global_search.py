"""Experimental. ``Karni.search``: the models one search box finds, and how a hit reads.

A model opts in next to its other Karni options::

    class Product(BaseModel):
        name = models.CharField(max_length=200)
        sku = models.CharField(max_length=40)

        class Karni:
            search = {
                "fields": ["name", "sku"],  # text fields the query is matched with
                "title": "name",            # what a hit shows (default: the first field)
                "subtitle": "sku",          # a second line (default: none)
                "weight": 2,                # this model's scores count double (default: 1)
            }

``GET /api/search/?q=`` (:mod:`karni.api.global_search`) searches every
model that opts in, each through the queryset its own list endpoint uses for
the request, so a model the caller cannot list never appears. Only declared
models are searched.

``fields`` are text fields of the model (``CharField``, ``TextField`` and
their subclasses). ``title`` and ``subtitle`` name a field of the model or a
path through foreign keys (``"supplier__name"``). ``weight`` is a number
above 0 that multiplies the model's scores, so its hits rank above or below
other models' hits.

Each searched field gets a GIN trigram index
(:class:`karni.fields.TrigramIndex`, PostgreSQL only, a no-op elsewhere) in
``Meta.indexes``, so ``makemigrations`` writes it with the model.
``karni check`` names a searched field whose table lacks it on PostgreSQL
(``W590``), with the command that adds it. A malformed declaration fails
``karni check`` with ``E430``, and a declared model that no routed
``BaseViewSet`` serves is ``W591``: search links each hit to its resource.

Override / escape hatch: ``search = None`` (or no declaration) leaves a
model out. A viewset's ``global_search_queryset`` builds that model's
search queryset (ranking, matching, title), and a subclass of
:class:`karni.api.global_search.GlobalSearchView` mounted before Karni's API
include replaces the endpoint.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from django.apps import apps
from django.core import checks
from django.core.exceptions import FieldDoesNotExist
from django.db import connections, models, router

from karni.exceptions import KarniImproperlyConfigured
from karni.meta import karni_option

__all__ = [
    "SEARCH_KEYS",
    "SearchDeclaration",
    "check_search_indexes",
    "indexed_fields",
    "search_declaration",
    "search_index_failures",
    "search_indexes",
    "searchable_models",
]

#: The keys ``Karni.search`` accepts.
SEARCH_KEYS: Final[frozenset[str]] = frozenset({"fields", "title", "subtitle", "weight"})


@dataclass(frozen=True)
class SearchDeclaration:
    """Experimental. A model's ``Karni.search``, validated and with its defaults filled in."""

    #: Text fields the query is matched with and ranked by.
    fields: tuple[str, ...]
    #: The field (or to-one path) a hit shows as its title.
    title: str
    #: The field (or to-one path) a hit shows under its title, or ``None``.
    subtitle: str | None
    #: What the model's scores are multiplied by, across models.
    weight: float


def _fail(model: type[models.Model], problem: str) -> KarniImproperlyConfigured:
    return KarniImproperlyConfigured(f"{model.__name__}.Karni.search {problem}", code="E430")


def _is_text(field: Any) -> bool:
    return isinstance(field, models.CharField | models.TextField) and not field.is_relation


def _field_names(model: type[models.Model]) -> str:
    return (
        ", ".join(field.name for field in model._meta.concrete_fields if _is_text(field)) or "none"
    )


def _searched_field(model: type[models.Model], name: Any) -> str:
    if not isinstance(name, str) or not name:
        raise _fail(model, f"fields lists {name!r}, which is not a field name.")
    try:
        field = model._meta.get_field(name)
    except FieldDoesNotExist:
        raise _fail(
            model,
            f"fields names {name!r}, which is not a field of {model.__name__}. Its text "
            f"fields: {_field_names(model)}.",
        ) from None
    if not getattr(field, "concrete", False) or not _is_text(field):
        raise _fail(
            model,
            f"fields names {name!r}, which is not a text field (CharField or TextField) of "
            f"{model.__name__}. Search matches and indexes text. Its text fields: "
            f"{_field_names(model)}.",
        )
    return name


def _shown_field(model: type[models.Model], key: str, path: Any) -> str:
    """``path`` when it is a concrete field, or a path through to-one relations to one."""
    if not isinstance(path, str) or not path:
        raise _fail(model, f"{key} must name a field, got {path!r}.")
    current: Any = model
    parts = path.split("__")
    for index, part in enumerate(parts):
        try:
            field = current._meta.get_field(part)
        except FieldDoesNotExist:
            raise _fail(
                model,
                f"{key} names {path!r}: {current.__name__} has no field {part!r}.",
            ) from None
        last = index == len(parts) - 1
        if field.many_to_many or field.one_to_many:
            raise _fail(
                model,
                f"{key} names {path!r}, which goes through the to-many relation {part!r}: a "
                "hit has one title. Name a field, or a path through foreign keys.",
            )
        if not last:
            if not field.is_relation or field.related_model is None:
                raise _fail(
                    model, f"{key} names {path!r}, but {part!r} is not a relation to follow."
                )
            current = field.related_model
        elif not getattr(field, "concrete", False):
            raise _fail(model, f"{key} names {path!r}, which is not a column.")
    return path


def search_declaration(model: type[models.Model]) -> SearchDeclaration | None:
    """Experimental. ``model``'s validated ``Karni.search``, or ``None`` when it does not opt in.

    Raises :class:`~karni.exceptions.KarniImproperlyConfigured` (``E430``) for
    a declaration that cannot work: an unknown key, a missing or empty
    ``fields``, a field that is not text, a title or subtitle that is not a
    field (or a path through foreign keys), a weight that is not a number
    above 0.
    """
    declared = karni_option(model, "search")
    if declared is None or declared is False:
        return None
    if not isinstance(declared, Mapping):
        raise _fail(
            model,
            f"must be a dict, got {declared!r}. Example: search = "
            '{"fields": ["name"], "title": "name"}.',
        )
    unknown = sorted(str(key) for key in set(declared) - SEARCH_KEYS)
    if unknown:
        raise _fail(
            model,
            f"has unknown keys: {', '.join(unknown)}. It accepts {', '.join(sorted(SEARCH_KEYS))}.",
        )
    raw_fields = declared.get("fields")
    if isinstance(raw_fields, str):
        raw_fields = [raw_fields]
    if not isinstance(raw_fields, list | tuple) or not raw_fields:
        raise _fail(
            model,
            f'needs "fields": the text fields to search, e.g. "fields": ["name"]. Its text '
            f"fields: {_field_names(model)}.",
        )
    fields = tuple(dict.fromkeys(_searched_field(model, name) for name in raw_fields))
    title = _shown_field(model, "title", declared.get("title", fields[0]))
    subtitle_value = declared.get("subtitle")
    subtitle = None if subtitle_value is None else _shown_field(model, "subtitle", subtitle_value)
    weight = declared.get("weight", 1)
    if isinstance(weight, bool) or not isinstance(weight, int | float) or weight <= 0:
        raise _fail(model, f"weight must be a number above 0, got {weight!r}.")
    return SearchDeclaration(fields, title, subtitle, float(weight))


def searchable_models() -> list[type[models.Model]]:
    """Experimental. Every installed model that declares ``Karni.search``, in app order."""
    found: list[type[models.Model]] = []
    for model in apps.get_models():
        if model._meta.proxy:
            continue
        declared = karni_option(model, "search")
        if declared is not None and declared is not False:
            found.append(model)
    return found


def indexed_fields(model: type[models.Model]) -> list[str]:
    """Experimental. The declared fields of ``model`` its own table holds, each a text column.

    The fields a trigram index is added for. Unknown names, and fields of a
    parent model's table, are left to ``E430`` and to the parent.
    """
    declared = karni_option(model, "search")
    if not isinstance(declared, Mapping):
        return []
    raw = declared.get("fields")
    names = [raw] if isinstance(raw, str) else raw
    if not isinstance(names, list | tuple):
        return []
    local = {field.name: field for field in model._meta.local_concrete_fields}
    return [
        name
        for name in dict.fromkeys(names)
        if isinstance(name, str) and name in local and _is_text(local[name])
    ]


def search_indexes(model: type[models.Model]) -> None:
    """Add a :class:`~karni.fields.TrigramIndex` to ``Meta.indexes`` for each searched field.

    Called from Karni's ``class_prepared`` hook for every concrete model, so
    ``makemigrations`` writes the indexes with the model.
    """
    from karni.fields.base import contribute_index
    from karni.fields.indexes import TrigramIndex

    for name in indexed_fields(model):
        contribute_index(
            model,
            TrigramIndex(fields=[name]),
            f"Karni.search: GIN trigram index on {name} (cross-model search, ILIKE and %)",
        )


# karni check: the indexes on PostgreSQL ------------------------------------------------

_TRIGRAM_COLUMNS: Final = """
SELECT t.relname, a.attname
FROM pg_index i
JOIN pg_class t ON t.oid = i.indrelid
JOIN pg_class ic ON ic.oid = i.indexrelid
JOIN pg_am am ON am.oid = ic.relam
JOIN LATERAL unnest(i.indkey::int2[], i.indclass::oid[]) AS k(attnum, opclass) ON true
JOIN pg_opclass oc ON oc.oid = k.opclass
JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
WHERE t.relname = ANY(%s)
  AND pg_table_is_visible(t.oid)
  AND oc.opcname IN ('gin_trgm_ops', 'gist_trgm_ops')
"""


def _covered(alias: str, tables: list[str]) -> tuple[set[str], set[tuple[str, str]]]:
    """``(tables that exist, (table, column) pairs a trigram index covers)`` on ``alias``."""
    connection = connections[alias]
    with connection.cursor() as cursor:
        existing = set(connection.introspection.table_names(cursor))
        cursor.execute(_TRIGRAM_COLUMNS, [tables])
        covered = {(str(table), str(column)) for table, column in cursor.fetchall()}
    return existing & set(tables), covered


def _fix(model: type[models.Model], field: Any) -> str:
    owner = field.model
    if owner._meta.managed:
        label = owner._meta.app_label
        return (
            f"Run `python manage.py makemigrations {label}` and `python manage.py migrate` "
            "(karni build writes the migration for an app built from karni.yaml): Karni adds "
            "the index to the model's Meta.indexes."
        )
    from karni.fields.indexes import TrigramIndex

    index = TrigramIndex(fields=[field.name])
    index.set_name_with_model(owner)
    return (
        f"{owner.__name__} is not managed by migrations, so create the index in its database: "
        f"CREATE INDEX {index.name} ON {owner._meta.db_table} USING gin ({field.column} "
        "gin_trgm_ops);"
    )


def check_search_indexes(
    search_models: Iterable[type[models.Model]] | None = None,
) -> list[checks.CheckMessage]:
    """Experimental. ``W590`` for each searched field whose table has no trigram index.

    Only on PostgreSQL, and only for tables that exist (before ``migrate``
    there is nothing to compare). A database that does not answer is skipped:
    ``karni check`` reports connection problems elsewhere. Codes in
    ``SILENCED_SYSTEM_CHECKS`` are left out.
    """
    from django.conf import settings

    from karni.exceptions import check_warning

    by_alias: dict[str, list[tuple[type[models.Model], Any]]] = {}
    for model in searchable_models() if search_models is None else search_models:
        try:
            declaration = search_declaration(model)
        except KarniImproperlyConfigured:
            continue  # E430's to report
        if declaration is None:
            continue
        for name in declaration.fields:
            field: Any = model._meta.get_field(name)
            alias = router.db_for_read(field.model)
            if connections[alias].vendor == "postgresql":
                by_alias.setdefault(alias, []).append((model, field))
    messages: list[checks.CheckMessage] = []
    for alias, pairs in sorted(by_alias.items()):
        tables = sorted({field.model._meta.db_table for _model, field in pairs})
        try:
            existing, covered = _covered(alias, tables)
        except Exception:  # noqa: BLE001 - a database that does not answer is not this check's
            continue
        for model, field in pairs:
            table = field.model._meta.db_table
            if table not in existing or (table, field.column) in covered:
                continue
            messages.append(
                check_warning(
                    "W590",
                    f"{model.__name__}.Karni.search searches {model.__name__}.{field.name}, "
                    f"but {table}.{field.column} has no trigram index on database {alias!r}: "
                    "every search reads the whole table.",
                    hint=_fix(model, field),
                    obj=model,
                )
            )
    silenced = set(getattr(settings, "SILENCED_SYSTEM_CHECKS", None) or [])
    return [message for message in messages if message.id not in silenced]


def search_index_failures(
    search_models: Iterable[type[models.Model]] | None = None,
) -> list[str]:
    """Experimental. :func:`check_search_indexes`, rendered one line each for ``karni check``."""
    lines: list[str] = []
    for message in check_search_indexes(search_models):
        text = f"{message.id}: {message.msg}"
        label = getattr(getattr(message.obj, "_meta", None), "label", None)
        if label is not None:
            text = f"{label}: {text}"
        if message.hint:
            text += f"\n\tHINT: {message.hint}"
        lines.append(text)
    return lines
