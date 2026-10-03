"""SQL-shape tests for PostgresSearchProvider (no PostgreSQL server needed).

Querysets are built and their compiled SQL inspected without executing them,
so these run on SQLite. Constructing ``SearchRank`` requires a PostgreSQL
*driver* to be importable (Django imports it for ``ArrayField``), hence the
driver guard — the behavioural leg lives in ``test_search.py`` and runs
against a real PostgreSQL service in CI.

Also here per the api contract: ``pluralize`` / ``kebab`` route-inflection
unit tests.
"""

from __future__ import annotations

import pytest
from django.contrib.postgres.search import SearchRank, TrigramSimilarity
from django.db.models.functions import Greatest

from karni.api.routers import default_route, kebab, pluralize
from karni.api.search.postgres import GinTrgmIndex, PostgresSearchProvider
from tests.testapp.models import Event

pytestmark = pytest.mark.django_db


def _has_postgres_driver() -> bool:
    try:
        import psycopg  # noqa: F401
    except ImportError:
        try:
            import psycopg2  # noqa: F401
        except ImportError:
            return False
    return True


requires_pg_driver = pytest.mark.skipif(
    not _has_postgres_driver(),
    reason="psycopg/psycopg2 required to construct SearchRank (pip install 'psycopg[binary]')",
)


# --- provider SQL shape -------------------------------------------------------


class SqlShapeProvider(PostgresSearchProvider):
    """Always emits PostgreSQL SQL, so its shape can be inspected on SQLite."""

    portable_fallback = False


@requires_pg_driver
def test_annotates_vector_rank_and_sim_and_rank_orders() -> None:
    queryset = SqlShapeProvider().search(
        queryset=Event.objects.all(), query="music", fields=["title", "description"]
    )
    assert {"vector", "rank", "sim"} <= set(queryset.query.annotations)
    assert isinstance(queryset.query.annotations["rank"], SearchRank)
    assert isinstance(queryset.query.annotations["sim"], Greatest)
    assert queryset.query.order_by == ("-rank", "-sim")


@requires_pg_driver
def test_compiled_sql_contains_fts_and_trigram_legs() -> None:
    queryset = SqlShapeProvider().search(
        queryset=Event.objects.all(), query="music", fields=["title", "description"]
    )
    sql = str(queryset.query)
    assert "to_tsvector" in sql
    assert "plainto_tsquery" in sql
    assert "@@" in sql  # full-text match ...
    assert "SIMILARITY(" in sql  # ... OR trigram similarity


@requires_pg_driver
def test_single_field_uses_plain_trigram_similarity() -> None:
    queryset = SqlShapeProvider().search(
        queryset=Event.objects.all(), query="music", fields=["title"]
    )
    assert isinstance(queryset.query.annotations["sim"], TrigramSimilarity)


@requires_pg_driver
def test_rank_order_false_annotates_but_keeps_incoming_ordering() -> None:
    queryset = SqlShapeProvider().search(
        queryset=Event.objects.order_by("title"),
        query="music",
        fields=["title"],
        rank_order=False,
    )
    assert {"vector", "rank", "sim"} <= set(queryset.query.annotations)
    assert queryset.query.order_by == ("title",)


@requires_pg_driver
def test_use_trigram_false_drops_the_similarity_leg() -> None:
    class FtsOnlyProvider(SqlShapeProvider):
        use_trigram = False

    queryset = FtsOnlyProvider().search(
        queryset=Event.objects.all(), query="music", fields=["title"]
    )
    assert "sim" not in queryset.query.annotations
    assert queryset.query.order_by == ("-rank",)
    assert "SIMILARITY(" not in str(queryset.query)


@requires_pg_driver
def test_similarity_threshold_is_an_overridable_class_attribute() -> None:
    class StrictProvider(SqlShapeProvider):
        similarity_threshold = 0.7

    queryset = StrictProvider().search(
        queryset=Event.objects.all(), query="music", fields=["title"]
    )
    assert "0.7" in str(queryset.query)


def test_noop_on_empty_query_or_fields() -> None:
    queryset = Event.objects.all()
    provider = PostgresSearchProvider()
    assert provider.search(queryset=queryset, query="", fields=["title"]) is queryset
    assert provider.search(queryset=queryset, query="music", fields=()) is queryset


# --- migration helpers --------------------------------------------------------


def test_gin_trgm_index_derives_opclasses_per_field() -> None:
    index = GinTrgmIndex(fields=["title", "description"], name="event_search_trgm")
    assert index.fields == ["title", "description"]
    assert index.opclasses == ["gin_trgm_ops", "gin_trgm_ops"]


def test_gin_trgm_index_deconstructs_and_reconstructs() -> None:
    index = GinTrgmIndex(fields=["title"], name="event_title_trgm")
    path, args, kwargs = index.deconstruct()
    assert path.endswith("GinTrgmIndex")
    assert kwargs["opclasses"] == ["gin_trgm_ops"]
    assert GinTrgmIndex(*args, **kwargs) == index


def test_gin_trgm_index_explicit_opclasses_win() -> None:
    index = GinTrgmIndex(fields=["title"], name="custom", opclasses=["text_pattern_ops"])
    assert index.opclasses == ["text_pattern_ops"]


@requires_pg_driver
def test_trigram_extension_is_reexported() -> None:
    from django.contrib.postgres import operations

    from karni.api.search import postgres

    assert postgres.TrigramExtension is operations.TrigramExtension


def test_unknown_module_attribute_raises_attribute_error() -> None:
    from karni.api.search import postgres

    with pytest.raises(AttributeError):
        postgres.DoesNotExist  # noqa: B018


# --- route inflection (contract-mandated location) ----------------------------


@pytest.mark.parametrize(
    ("word", "plural"),
    [
        ("event", "events"),
        ("venue", "venues"),
        ("category", "categories"),  # y after consonant
        ("day", "days"),  # y after vowel stays
        ("bus", "buses"),
        ("box", "boxes"),
        ("quiz", "quizes"),  # contract rule: z -> es (naive by design)
        ("church", "churches"),
        ("dish", "dishes"),
        ("event-category", "event-categories"),
    ],
)
def test_pluralize(word: str, plural: str) -> None:
    assert pluralize(word) == plural


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Venue", "venue"),
        ("EventCategory", "event-category"),
        ("APIKey", "api-key"),
    ],
)
def test_kebab(name: str, expected: str) -> None:
    assert kebab(name) == expected


def test_default_route_is_kebab_plural_of_model_name() -> None:
    assert default_route(Event) == "events"


def test_default_provider_falls_back_on_non_postgres_databases() -> None:
    """sqlite (local development) cannot run full-text SQL: the default falls back."""
    Event.objects.create(title="Jazz night", starts_at="2030-01-01T20:00Z")
    Event.objects.create(title="Chess club", starts_at="2030-01-02T20:00Z")
    found = PostgresSearchProvider().search(
        queryset=Event.objects.all(), query="jazz", fields=["title"]
    )
    assert [e.title for e in found] == ["Jazz night"]
