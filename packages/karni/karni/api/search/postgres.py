"""PostgreSQL full-text + trigram search provider (the default).

Setup in a project (documented in ``docs/api.md``): PostgreSQL needs the
``pg_trgm`` extension for the trigram leg, plus (optionally) a GIN index per
searched column. Both fit in one migration::

    from karni.api.search.postgres import GinTrgmIndex, TrigramExtension

    class Migration(migrations.Migration):
        operations = [
            TrigramExtension(),
            migrations.AddIndex(
                model_name="event",
                index=GinTrgmIndex(fields=["title"], name="event_title_trgm"),
            ),
        ]

``TrigramExtension`` is re-exported lazily (module ``__getattr__``) so this
module stays importable without a PostgreSQL driver installed; resolving the
name requires ``psycopg`` (or ``psycopg2``), as does actually running
:meth:`PostgresSearchProvider.search`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import (
    SearchQuery,
    SearchRank,
    SearchVector,
    TrigramSimilarity,
)
from django.db import connections
from django.db.models import Expression, Q, QuerySet
from django.db.models.functions import Greatest

from karni.api.search import SearchProvider

# TrigramExtension is a lazy re-export resolved by module __getattr__ below,
# so pyflakes cannot see its definition here.
__all__ = ["GinTrgmIndex", "PostgresSearchProvider", "TrigramExtension"]  # noqa: F822


class PostgresSearchProvider(SearchProvider):
    """Full-text search with a trigram-similarity fallback, in one lazy queryset.

    :meth:`search` annotates ``vector`` (``SearchVector`` over the fields),
    ``rank`` (``SearchRank``) and — unless :attr:`use_trigram` is ``False`` —
    ``sim`` (the greatest ``TrigramSimilarity`` across the fields), then keeps
    rows matching the full-text query OR exceeding
    :attr:`similarity_threshold`. The trigram leg catches prefixes and typos
    that word-stemming full-text search misses. Nothing executes until the
    queryset is evaluated, so pagination and further filtering compose as
    usual.

    When ``rank_order`` is true (no explicit ``?ordering=`` on the request)
    results are ordered by ``-rank`` then ``-sim``; otherwise the incoming
    ordering is left untouched so an explicit ``?ordering=`` wins.

    Override / escape hatch: subclass and adjust :attr:`similarity_threshold`
    or :attr:`use_trigram` (or override :meth:`search`), then point the
    ``KARNI_SEARCH_PROVIDER`` setting at your subclass.
    """

    similarity_threshold: float = 0.3
    """Minimum trigram similarity for a non-full-text match to be kept."""

    use_trigram: bool = True
    #: On a non-PostgreSQL database (sqlite in local development), delegate to
    #: SimpleSearchProvider instead of emitting SQL the database cannot run.
    portable_fallback: bool = True
    """Set ``False`` to drop the trigram leg (no ``pg_trgm`` requirement)."""

    def search(
        self,
        *,
        queryset: QuerySet[Any],
        query: str,
        fields: Sequence[str],
        view: Any | None = None,
        rank_order: bool = True,
    ) -> QuerySet[Any]:
        """Annotate, filter and (optionally) rank-order ``queryset``.

        On a non-PostgreSQL database (sqlite for local development, for
        example) full-text SQL cannot run, so the search falls back to
        :class:`~karni.api.search.simple.SimpleSearchProvider` instead of
        failing. Set :attr:`portable_fallback` to ``False`` to always emit
        PostgreSQL SQL (e.g. to inspect it), or set ``KARNI_SEARCH_PROVIDER``.
        """
        if not query or not fields:
            return queryset
        if self.portable_fallback and connections[queryset.db].vendor != "postgresql":
            from karni.api.search.simple import SimpleSearchProvider

            return SimpleSearchProvider().search(
                queryset=queryset, query=query, fields=fields, view=view, rank_order=rank_order
            )
        vector = SearchVector(*fields)
        search_query = SearchQuery(query)
        annotations: dict[str, Expression] = {
            "vector": vector,
            "rank": SearchRank(vector, search_query),
        }
        condition = Q(vector=search_query)
        if self.use_trigram:
            similarities = [TrigramSimilarity(field, query) for field in fields]
            annotations["sim"] = (
                similarities[0] if len(similarities) == 1 else Greatest(*similarities)
            )
            condition = condition | Q(sim__gt=self.similarity_threshold)
        result = queryset.annotate(**annotations).filter(condition)
        if rank_order:
            ordering = ("-rank", "-sim") if self.use_trigram else ("-rank",)
            result = result.order_by(*ordering)
        return result


class GinTrgmIndex(GinIndex):
    """``GinIndex`` preconfigured with ``gin_trgm_ops`` for every field.

    ``GinTrgmIndex(fields=["title"], name="event_title_trgm")`` is equivalent
    to ``GinIndex(fields=["title"], name="...", opclasses=["gin_trgm_ops"])``
    and makes the provider's trigram leg an index scan. Requires the
    ``pg_trgm`` extension (see :class:`TrigramExtension`). A ``name`` is
    mandatory because Django requires named indexes when opclasses are used.

    Override / escape hatch: pass ``opclasses=[...]`` explicitly to replace
    the derived opclasses, or use a plain ``GinIndex`` directly.
    """

    def __init__(self, *, fields: Sequence[str] = (), name: str, **kwargs: Any) -> None:
        kwargs.setdefault("opclasses", ["gin_trgm_ops"] * len(fields))
        super().__init__(fields=fields, name=name, **kwargs)


def __getattr__(name: str) -> Any:
    """Lazily re-export ``TrigramExtension``.

    ``django.contrib.postgres.operations`` imports the PostgreSQL driver at
    module level, so the re-export resolves on first attribute access instead
    of at import time — keeping ``karni`` importable with only core
    dependencies installed.
    """
    if name == "TrigramExtension":
        try:
            from django.contrib.postgres.operations import TrigramExtension
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise ImportError(
                "TrigramExtension requires a PostgreSQL driver; "
                "install psycopg (pip install 'psycopg[binary]')."
            ) from exc
        return TrigramExtension
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
