"""PostgreSQL-only guarantees: tsvector, GIN/BRIN indexes, arrays, extensions.

Skipped on SQLite (the default suite); CI's PostgreSQL step runs them
(``.github/ci/karni_postgres_settings.py``). Index use is proven with
``EXPLAIN`` under ``enable_seqscan = off``: the planner may only pick the
index if the index can answer the query.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.db import DatabaseError, connection, models, transaction
from django.test.utils import isolate_apps

from karni.api.search.postgres import PostgresSearchProvider
from karni.exceptions import KarniImproperlyConfigured
from karni.fields import ensure_extension
from tests.fields.conftest import product_row, raw_insert, raw_update
from tests.fieldsapp.models import LogEntry, Product

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="PostgreSQL-only: tsvector, GIN/BRIN, arrays and extensions (CI's Postgres step)",
    ),
]


def _plan(sql: str, params: list[Any] | None = None) -> str:
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL enable_seqscan = off")
        cursor.execute(f"EXPLAIN {sql}", params or [])
        return "\n".join(row[0] for row in cursor.fetchall())


def _index_types(table: str) -> dict[str, str]:
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, table)
    return {name: str(info.get("type")) for name, info in constraints.items() if info["index"]}


def test_gin_and_brin_indexes_exist() -> None:
    product = _index_types("fieldsapp_product")
    assert sorted(t for t in product.values() if t == "gin") == ["gin", "gin"]
    assert "brin" in _index_types("fieldsapp_logentry").values()
    created = LogEntry._meta.get_field("created_at")
    assert not created.db_index  # the B-tree was replaced, not duplicated


def test_search_column_is_kept_in_sync_by_the_database_even_for_raw_sql() -> None:
    row = product_row(name="Walnut desk", description="solid oak top")
    raw_insert("fieldsapp_product", row)
    raw_update("fieldsapp_product", "description", "maple top", row["id"])
    with connection.cursor() as cursor:
        cursor.execute("SELECT search::text FROM fieldsapp_product WHERE id = %s", [row["id"]])
        vector = cursor.fetchone()[0]
    assert "'maple'" in vector and "'oak'" not in vector
    assert "'walnut':1A" in vector  # name carries weight A
    with pytest.raises(DatabaseError, match="generated column"), transaction.atomic():
        raw_update("fieldsapp_product", "search", "x", row["id"])  # nobody writes it


def test_the_search_provider_matches_through_the_search_field_index() -> None:
    raw_insert("fieldsapp_product", product_row(name="Walnut desk", description="oak"))
    raw_insert("fieldsapp_product", product_row(name="Steel chair", description="metal"))
    provider = PostgresSearchProvider()
    found = provider.search(queryset=Product.objects.all(), query="walnu", fields=["search"])
    assert [p.name for p in found] == ["Walnut desk"]  # each word is a prefix
    covered = provider.search(
        queryset=Product.objects.all(), query="oak", fields=["name", "description"]
    )
    assert "search" in str(covered.query) and "to_tsvector" not in str(covered.query)
    # Every row, so the planner cannot answer with the live-rows slug index instead.
    everything = Product.objects.without("soft_delete", reason="prove the GIN plan")
    planned = provider.search(queryset=everything, query="walnu", fields=["search"])
    sql, params = planned.query.sql_with_params()
    assert "fieldsapp_p_search_335b55_gin" in _plan(sql, list(params))


def test_queried_json_uses_its_gin_index() -> None:
    plan = _plan("""SELECT id FROM fieldsapp_product WHERE meta @> '{"colour": "red"}'""")
    assert "fieldsapp_p_meta_db0891_gin" in plan


@isolate_apps("tests.fieldsapp")
def test_array_field_gets_a_gin_index_that_serves_contains() -> None:
    from karni.fields import ArrayField

    class Article(models.Model):
        tags = ArrayField(models.CharField(max_length=20))

        class Meta:
            app_label = "fieldsapp"

    with connection.schema_editor() as editor:
        editor.create_model(Article)
    raw_insert("fieldsapp_article", {"tags": ["django", "postgres"]})
    assert "_gin" in _plan(
        "SELECT id FROM fieldsapp_article WHERE tags @> ARRAY['django']::varchar[]"
    )
    assert Article.objects.filter(tags__contains=["postgres"]).count() == 1


def test_btree_gist_is_created_and_creation_is_idempotent() -> None:
    with connection.schema_editor() as editor:
        ensure_extension(editor, "btree_gist")
        ensure_extension(editor, "btree_gist")
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'btree_gist'")
        assert cursor.fetchone() is not None


def test_a_role_without_create_gets_the_exact_fix() -> None:
    """A role lacking CREATE on the database cannot create a trusted extension: E966 says how."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'seg'")
        if cursor.fetchone() is not None:
            pytest.skip("seg is already installed in the test database")
        cursor.execute("CREATE ROLE karni_fields_noext NOLOGIN")  # rolled back with the test
    with pytest.raises(KarniImproperlyConfigured, match="E966") as caught, transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE karni_fields_noext")
        with connection.schema_editor(atomic=False) as editor:
            ensure_extension(editor, "seg")
    message = str(caught.value)
    assert "CREATE EXTENSION IF NOT EXISTS seg;" in message
    assert "permission denied" in message.lower()
