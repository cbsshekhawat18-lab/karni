"""Extensions are created by migration, vendor-guarded, and a refusal names the exact SQL."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

import pytest

from karni.exceptions import KarniImproperlyConfigured
from karni.fields import CreateExtension, ensure_extension
from karni.fields.extensions import extension_fix

migration = importlib.import_module("karni.accounts.migrations.0005_btree_gist")


class _Cursor:
    def __init__(self, installed: bool) -> None:
        self.installed = installed

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.sql = sql

    def fetchone(self) -> Any:
        return (1,) if self.installed else None


def _editor(
    vendor: str, *, installed: bool = False, fail: Exception | None = None, version: int = 170000
) -> Any:
    calls: list[str] = []

    def execute(sql: str) -> None:
        calls.append(sql)
        if fail is not None:
            raise fail

    connection = SimpleNamespace(
        vendor=vendor,
        pg_version=version,
        settings_dict={"NAME": "shop", "USER": "shop_app"},
        cursor=lambda: _Cursor(installed),
    )
    return SimpleNamespace(connection=connection, execute=execute, calls=calls)


def test_other_databases_are_untouched() -> None:
    editor = _editor("sqlite")
    ensure_extension(editor, "btree_gist")
    assert editor.calls == []


def test_postgresql_creates_a_missing_extension_once() -> None:
    editor = _editor("postgresql")
    ensure_extension(editor, "btree_gist")
    assert editor.calls == ['CREATE EXTENSION IF NOT EXISTS "btree_gist"']
    present = _editor("postgresql", installed=True)
    ensure_extension(present, "btree_gist")
    assert present.calls == []  # a DBA created it: no CREATE, no permission needed


def test_a_refused_trusted_extension_names_both_fixes() -> None:
    editor = _editor("postgresql", fail=RuntimeError("permission denied to create extension"))
    with pytest.raises(KarniImproperlyConfigured, match="E966") as caught:
        ensure_extension(editor, "btree_gist")
    message = str(caught.value)
    assert "`CREATE EXTENSION IF NOT EXISTS btree_gist;`" in message
    assert '`GRANT CREATE ON DATABASE "shop" TO "shop_app";`' in message
    assert "permission denied" in message


def test_an_untrusted_or_old_server_extension_needs_a_superuser() -> None:
    untrusted = extension_fix("postgres_fdw", _editor("postgresql").connection)
    assert "only a superuser" in untrusted and "GRANT" not in untrusted
    old_server = extension_fix("btree_gist", _editor("postgresql", version=120000).connection)
    assert "GRANT" not in old_server  # trusted extensions arrived in PostgreSQL 13


def test_karni_accounts_creates_btree_gist() -> None:
    (operation,) = migration.Migration.operations
    assert isinstance(operation, CreateExtension) and operation.name == "btree_gist"
    assert operation.deconstruct() == ("karni.fields.CreateExtension", ["btree_gist"], {})
    assert migration.Migration.dependencies == [("karni_accounts", "0004_pg_trgm")]
    editor = _editor("postgresql")
    operation.database_forwards("karni_accounts", editor, None, None)
    operation.database_backwards("karni_accounts", editor, None, None)  # never drops
    assert editor.calls == ['CREATE EXTENSION IF NOT EXISTS "btree_gist"']
