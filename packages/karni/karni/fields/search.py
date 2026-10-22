"""Full-text search as a column: a generated ``tsvector`` with a GIN index.

``SearchField(sources=["title", "description"])`` is a stored generated
column the database computes from the source fields on every write (ORM,
bulk update, raw SQL alike), so it can never drift from them::

    class Event(BaseModel):
        title = models.CharField(max_length=200)
        description = models.TextField()
        search = SearchField(sources=["title", "description"], config="english")

    class EventViewSet(BaseViewSet):
        model = Event
        search_fields = ["search"]          # ?search= uses the column and its index

On PostgreSQL the column is ``to_tsvector(config, ...)`` (``setweight`` per
source when ``weights={"title": "A", "description": "B"}``) with a GIN index,
and the default search provider matches and ranks on it instead of
computing a vector per row. Everywhere else the column is the sources'
plain text and the GIN index is skipped; the portable search provider
searches the source fields (``karni.W964`` says so).

The column is never written, never in the API (it is not data, it is an
index of data) and never in factories.

Override / escape hatch: ``config`` is any PostgreSQL text search
configuration (``simple`` by default: no stemming, any language); a plain
``GeneratedField(expression=SearchVector(...), output_field=SearchVectorField(),
db_persist=True)`` plus a ``GinIndex`` is the hand-written equivalent.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models import F, Func

from karni.exceptions import KarniImproperlyConfigured
from karni.fields.base import PUBLIC_PATH, KarniField
from karni.fields.indexes import GinIndex

__all__ = ["SearchDocument", "SearchField", "expand_search_fields", "search_field_for"]

_CONFIG = re.compile(r"^[a-z_][a-z0-9_.]*$")
_WEIGHTS = frozenset("ABCD")


class _TSVectorColumn(SearchVectorField):
    """``tsvector`` on PostgreSQL, plain text elsewhere (the GeneratedField's output)."""

    def db_type(self, connection: Any) -> str:
        return "tsvector" if connection.vendor == "postgresql" else "text"


class SearchDocument(Func):
    """The expression a :class:`SearchField` column is generated from."""

    def __init__(self, sources: Sequence[str], config: str, weights: Mapping[str, str]) -> None:
        self.sources = tuple(sources)
        self.config = config
        self.weights = dict(weights)
        super().__init__(*(F(name) for name in self.sources), output_field=_TSVectorColumn())

    def _texts(self, compiler: Any, connection: Any) -> tuple[list[str], list[Any]]:
        texts: list[str] = []
        params: list[Any] = []
        for expression in self.get_source_expressions():
            sql, sql_params = compiler.compile(expression)
            texts.append(f"COALESCE(CAST({sql} AS text), '')")
            params.extend(sql_params)
        return texts, params

    def as_sql(self, compiler: Any, connection: Any, **extra: Any) -> tuple[str, list[Any]]:
        texts, params = self._texts(compiler, connection)
        return " || ' ' || ".join(texts), params

    def as_postgresql(self, compiler: Any, connection: Any, **extra: Any) -> tuple[str, list[Any]]:
        texts, params = self._texts(compiler, connection)
        config = f"'{self.config}'::regconfig"
        if not self.weights:
            joined = " || ' ' || ".join(texts)
            return f"to_tsvector({config}, {joined})", params
        parts = []
        for name, text in zip(self.sources, texts, strict=True):
            vector = f"to_tsvector({config}, {text})"
            weight = self.weights.get(name)
            parts.append(f"setweight({vector}, '{weight}')" if weight else vector)
        return "(" + " || ".join(parts) + ")", params


class SearchField(KarniField, models.GeneratedField):
    """A generated full-text column over ``sources`` (see the module docstring)."""

    backend_support = "degrades"
    plain_django = "models.GeneratedField(SearchVector(...)) + GinIndex"

    def __init__(
        self,
        *,
        sources: Sequence[str],
        config: str = "simple",
        weights: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        if isinstance(sources, str) or not sources:
            raise KarniImproperlyConfigured(
                f"SearchField(sources={sources!r}): list the fields to search, e.g. "
                'SearchField(sources=["title", "description"]).',
                code="E963",
            )
        if not _CONFIG.match(config):
            raise KarniImproperlyConfigured(
                f"SearchField(config={config!r}): name a PostgreSQL text search configuration "
                "such as 'simple' or 'english'.",
                code="E963",
            )
        weights = dict(weights or {})
        bad = {name: weight for name, weight in weights.items() if weight not in _WEIGHTS}
        stray = sorted(set(weights) - set(sources))
        if bad or stray:
            raise KarniImproperlyConfigured(
                f"SearchField(weights={weights!r}): weights map source fields to 'A', 'B', 'C' "
                f"or 'D'{'; not sources: ' + ', '.join(stray) if stray else ''}.",
                code="E963",
            )
        self.sources = tuple(sources)
        self.config = config
        self.weights = weights
        for key in ("expression", "output_field", "db_persist"):
            kwargs.pop(key, None)
        super().__init__(
            expression=SearchDocument(self.sources, config, weights),
            output_field=_TSVectorColumn(),
            db_persist=True,
            **kwargs,
        )

    def karni_indexes(self, model: type[models.Model]) -> list[tuple[Any, str]]:
        return [
            (
                GinIndex(fields=[self.name]),
                f"SearchField over {', '.join(self.sources)}: ?search= matches through this index",
            )
        ]

    def karni_column(self) -> str:
        return (
            f"SearchField: tsvector generated from {', '.join(self.sources)} "
            f"(config {self.config}), kept in sync by the database"
        )

    def postgres_only_text(self) -> str:
        return (
            "the tsvector column and its GIN index (here the column holds plain text and "
            "?search= falls back to matching the source fields)"
        )

    def deconstruct(self) -> tuple[str, str, list[Any], dict[str, Any]]:
        name, _path, args, kwargs = super().deconstruct()
        for key in ("expression", "output_field", "db_persist"):
            kwargs.pop(key, None)
        kwargs["sources"] = list(self.sources)
        if self.config != "simple":
            kwargs["config"] = self.config
        if self.weights:
            kwargs["weights"] = dict(self.weights)
        return name, f"{PUBLIC_PATH}.SearchField", args, kwargs


def search_field_for(model: type[models.Model], names: Sequence[str]) -> SearchField | None:
    """The SearchField ``names`` asks for: named directly, or covering every name as a source."""
    fields = [field for field in model._meta.concrete_fields if isinstance(field, SearchField)]
    for field in fields:
        if field.name in names:
            return field
    plain = {str(name) for name in names}
    for field in fields:
        if plain and plain <= set(field.sources):
            return field
    return None


def expand_search_fields(model: type[models.Model], names: Sequence[str]) -> list[str]:
    """``names`` with each SearchField replaced by its source fields (portable search)."""
    by_name = {
        field.name: field for field in model._meta.concrete_fields if isinstance(field, SearchField)
    }
    expanded: list[str] = []
    for name in names:
        field = by_name.get(str(name))
        for item in field.sources if field is not None else (name,):
            if item not in expanded:
                expanded.append(item)
    return expanded
