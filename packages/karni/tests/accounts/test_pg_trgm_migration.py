"""The ``pg_trgm`` migration: creates the extension on PostgreSQL, does nothing elsewhere."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

import pytest

migration = importlib.import_module("karni.accounts.migrations.0004_pg_trgm")


def _editor(vendor: str, fail: Exception | None = None) -> Any:
    calls: list[str] = []

    def execute(sql: str) -> None:
        calls.append(sql)
        if fail is not None:
            raise fail

    return SimpleNamespace(connection=SimpleNamespace(vendor=vendor), execute=execute, calls=calls)


def test_other_databases_are_untouched() -> None:
    editor = _editor("sqlite")
    migration.create_pg_trgm(None, editor)
    assert editor.calls == []


def test_postgresql_gets_the_extension() -> None:
    editor = _editor("postgresql")
    migration.create_pg_trgm(None, editor)
    assert editor.calls == ["CREATE EXTENSION IF NOT EXISTS pg_trgm"]


def test_a_refusal_names_the_fix() -> None:
    editor = _editor("postgresql", fail=RuntimeError("permission denied to create extension"))
    with pytest.raises(RuntimeError, match="CREATE EXTENSION IF NOT EXISTS pg_trgm;") as caught:
        migration.create_pg_trgm(None, editor)
    assert "permission denied" in str(caught.value)
