"""``makemigrations`` re-creates a generated field whose definition changed."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.management import call_command, get_commands, load_command_class
from django.db import connection, models
from django.db.migrations import operations as ops
from django.db.migrations.autodetector import MigrationAutodetector
from django.db.migrations.state import ModelState, ProjectState
from django.db.models.functions import Upper

from karni.fields import SearchField
from karni.fields.indexes import GinIndex
from karni.migration_autodetector import KarniAutodetector, attached_to_field

APP = "shelfapp"


def _state(*fields: tuple[str, models.Field], **options: Any) -> ProjectState:
    base: list[tuple[str, models.Field]] = [
        ("id", models.BigAutoField(primary_key=True)),
        ("title", models.CharField(max_length=40)),
        ("note", models.TextField(blank=True)),
    ]
    state = ProjectState()
    state.add_model(ModelState(APP, "Shelf", [*base, *fields], options=options))
    return state


def _search(*sources: str, **kwargs: Any) -> tuple[str, models.Field]:
    return ("search", SearchField(sources=list(sources), **kwargs))


def _gin() -> dict[str, Any]:
    return {"indexes": [GinIndex(fields=["search"], name="shelf_search_gin")]}


def _changes(
    before: ProjectState, after: ProjectState, detector: type[MigrationAutodetector]
) -> list[str]:
    found = detector(before, after)._detect_changes()
    return [type(op).__name__ for migration in found.get(APP, []) for op in migration.operations]


def test_a_changed_search_field_is_removed_and_added_with_its_index() -> None:
    before = _state(_search("title"), **_gin())
    after = _state(_search("title", "note"), **_gin())
    assert _changes(before, after, MigrationAutodetector) == ["AlterField"]  # what Django writes
    assert _changes(before, after, KarniAutodetector) == [
        "RemoveIndex",
        "RemoveField",
        "AddField",
        "AddIndex",
    ]


@pytest.mark.parametrize(
    "other",
    [
        _search("title", config="english"),
        _search("title", weights={"title": "A"}),
    ],
)
def test_every_part_of_the_definition_counts(other: tuple[str, models.Field]) -> None:
    before = _state(_search("title"))
    assert _changes(before, _state(other), KarniAutodetector) == ["RemoveField", "AddField"]


def test_a_plain_generated_field_with_another_expression_or_persistence() -> None:
    def made(expression: Any, persist: bool = True) -> ProjectState:
        field = models.GeneratedField(
            expression=expression, output_field=models.TextField(), db_persist=persist
        )
        return _state(("shout", field))

    base = made(Upper("title"))
    assert _changes(base, made(Upper("note")), KarniAutodetector) == ["RemoveField", "AddField"]
    assert _changes(base, made(Upper("title"), persist=False), KarniAutodetector) == [
        "RemoveField",
        "AddField",
    ]
    assert _changes(base, made(Upper("title")), KarniAutodetector) == []


def test_a_change_that_is_not_in_the_column_keeps_the_column() -> None:
    before = _state(_search("title"), **_gin())
    labelled = ("search", SearchField(sources=["title"], verbose_name="Find", help_text="words"))
    assert _changes(before, _state(labelled, **_gin()), KarniAutodetector) == ["AlterField"]
    assert _changes(before, _state(_search("title"), **_gin()), KarniAutodetector) == []


def test_a_constraint_that_names_the_field_goes_and_comes_back() -> None:
    check = models.CheckConstraint(condition=models.Q(shout__gt=""), name="shout_not_empty")
    other = models.UniqueConstraint(fields=["title"], name="title_once")

    def made(expression: Any) -> ProjectState:
        field = models.GeneratedField(
            expression=expression, output_field=models.TextField(), db_persist=True
        )
        return _state(("shout", field), constraints=[check, other])

    names = _changes(made(Upper("title")), made(Upper("note")), KarniAutodetector)
    assert names == ["RemoveConstraint", "RemoveField", "AddField", "AddConstraint"]
    options = {"indexes": [], "constraints": [check, other]}
    assert attached_to_field(options, "shout") == ([], [check])


def _shouting(expression: Any, together: set[tuple[str, str]]) -> ProjectState:
    shout = models.GeneratedField(
        expression=expression, output_field=models.CharField(max_length=40), db_persist=True
    )
    return _state(("shout", shout), unique_together=together)


def test_a_unique_together_that_names_the_field_goes_and_comes_back() -> None:
    together = {("shout", "title"), ("title", "note")}
    before, after = _shouting(Upper("title"), together), _shouting(Upper("note"), together)
    found = KarniAutodetector(before, after)._detect_changes()
    operations = [op for migration in found[APP] for op in migration.operations]
    assert [type(op).__name__ for op in operations] == [
        "AlterUniqueTogether",
        "RemoveField",
        "AddField",
        "AlterUniqueTogether",
    ]
    assert operations[0].unique_together == {("title", "note")}  # the other entry stays
    assert operations[-1].unique_together == together


def test_a_unique_together_changed_in_the_same_run_follows_the_new_column() -> None:
    before = _shouting(Upper("title"), {("shout", "title")})
    after = _shouting(Upper("note"), {("shout", "note")})
    found = KarniAutodetector(before, after)._detect_changes()
    operations = [op for migration in found[APP] for op in migration.operations]
    assert [type(op).__name__ for op in operations] == [
        "AlterUniqueTogether",
        "RemoveField",
        "AddField",
        "AlterUniqueTogether",
    ]
    assert operations[0].unique_together == set()
    assert operations[-1].unique_together == {("shout", "note")}
    added = _changes(_shouting(Upper("title"), set()), after, KarniAutodetector)
    assert added == ["RemoveField", "AddField", "AlterUniqueTogether"]


@pytest.mark.django_db(transaction=True)  # SQLite's schema editor runs outside a transaction
def test_a_unique_together_on_the_field_survives_the_migration_both_ways() -> None:
    """SQLite refuses to drop a column a unique index names, PostgreSQL drops the index.

    Without the operations around the column the migration fails on SQLite and leaves the
    table without its unique constraint on PostgreSQL, forwards and backwards.
    """
    together = {("shout", "title")}
    before, after = _shouting(Upper("title"), together), _shouting(Upper("note"), together)
    found = KarniAutodetector(before, after)._detect_changes()
    operations = [op for migration in found[APP] for op in migration.operations]
    table = f"{APP}_shelf"

    def unique_columns() -> list[list[str]]:
        with connection.cursor() as cursor:
            found = connection.introspection.get_constraints(cursor, table)
        return sorted(
            sorted(item["columns"])
            for item in found.values()
            if item["unique"] and not item["primary_key"]
        )

    states = [ProjectState()]
    creating = ops.CreateModel(
        "Shelf",
        list(before.models[APP, "shelf"].fields.items()),
        options=before.models[APP, "shelf"].options,
    )
    try:
        with connection.schema_editor() as editor:
            created = states[0].clone()
            creating.state_forwards(APP, created)
            creating.database_forwards(APP, editor, states[0], created)
            states = [created]
        assert unique_columns() == [["shout", "title"]]
        with connection.schema_editor() as editor:
            for op in operations:
                new = states[-1].clone()
                op.state_forwards(APP, new)
                op.database_forwards(APP, editor, states[-1], new)
                states.append(new)
        assert unique_columns() == [["shout", "title"]]
        with connection.schema_editor() as editor:
            for index in reversed(range(len(operations))):
                operations[index].database_backwards(APP, editor, states[index + 1], states[index])
        assert unique_columns() == [["shout", "title"]]
    finally:
        with connection.schema_editor() as editor:
            editor.execute(f"DROP TABLE IF EXISTS {table}")


def test_a_field_that_is_not_generated_is_left_to_django() -> None:
    before = _state()
    after = _state(("code", models.CharField(max_length=5)))
    assert _changes(before, after, KarniAutodetector) == ["AddField"]


def test_makemigrations_and_migrate_use_it() -> None:
    assert get_commands()["makemigrations"] == "karni"
    assert get_commands()["migrate"] == "karni"
    for name in ("makemigrations", "migrate"):
        assert load_command_class("karni", name).autodetector is KarniAutodetector
    call_command("check")  # Django's commands.E001: both commands share one detector


@pytest.mark.django_db
@pytest.mark.skipif(connection.vendor != "postgresql", reason="a tsvector column needs PostgreSQL")
def test_the_migration_applies_searches_and_reverses_on_postgresql() -> None:
    before = _state(_search("title"), **_gin())
    after = _state(_search("title", "note"), **_gin())
    found = KarniAutodetector(before, after)._detect_changes()
    operations = [op for migration in found[APP] for op in migration.operations]
    assert not any(isinstance(op, ops.AlterField) for op in operations)

    created = ProjectState()
    created.add_model(before.models[APP, "shelf"].clone())
    table = f"{APP}_shelf"

    def indexes() -> list[str]:
        with connection.cursor() as cursor:
            return [
                row["indexname"]
                for row in _rows(
                    cursor, "select indexname from pg_indexes where tablename = %s", table
                )
            ]

    state = ProjectState()
    with connection.schema_editor() as editor:
        creating = ops.CreateModel(
            "Shelf",
            [(n, f) for n, f in before.models[APP, "shelf"].fields.items()],
            options=before.models[APP, "shelf"].options,
        )
        new = state.clone()
        creating.state_forwards(APP, new)
        creating.database_forwards(APP, editor, state, new)
        state = new
    with connection.cursor() as cursor:
        cursor.execute(f"insert into {table} (title, note) values ('Oak', 'walnut ledge')")
    assert "shelf_search_gin" in indexes()

    states = [state]
    with connection.schema_editor() as editor:
        for op in operations:
            new = states[-1].clone()
            op.state_forwards(APP, new)
            op.database_forwards(APP, editor, states[-1], new)
            states.append(new)
    with connection.cursor() as cursor:
        cursor.execute(f"select count(*) from {table} where search @@ to_tsquery('walnut')")
        assert cursor.fetchone() == (1,)  # the new source is searched, the old row recomputed
    assert "shelf_search_gin" in indexes()

    with connection.schema_editor() as editor:
        for index in reversed(range(len(operations))):
            operations[index].database_backwards(APP, editor, states[index + 1], states[index])
    with connection.cursor() as cursor:
        cursor.execute(f"select count(*) from {table} where search @@ to_tsquery('walnut')")
        assert cursor.fetchone() == (0,)  # back to title alone
    assert "shelf_search_gin" in indexes()


def _rows(cursor: Any, sql: str, *params: Any) -> list[dict[str, Any]]:
    cursor.execute(sql, params)
    names = [column.name for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
