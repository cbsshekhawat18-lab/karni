"""Migration 0006: commerce's edited emails move to karni.notify, nothing lost."""

from __future__ import annotations

import datetime as dt
import importlib
from typing import Any

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.state import StateApps
from karni.exceptions import KarniError

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE = [("karni_commerce", "0005_drop_setting"), ("notify", "0001_initial")]
AFTER = [("karni_commerce", "0006_email_templates_to_notify")]
MOVE = importlib.import_module("karni_commerce.migrations.0006_email_templates_to_notify")


def _at(targets: list[tuple[str, str]]) -> StateApps:
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    executor.loader.build_graph()
    return executor.loader.project_state(targets).apps


def _leave_at_latest() -> None:
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def test_each_edited_email_moves_with_its_dates() -> None:
    try:
        old = _at(BEFORE)
        source = old.get_model("karni_commerce", "EmailTemplate")
        target = old.get_model("notify", "EmailTemplate")
        written = dt.datetime(2026, 1, 2, 3, 4, tzinfo=dt.UTC)
        moved = source.objects.create(kind="commerce.order_paid", subject="Paid", text="Thanks")
        source.objects.filter(pk=moved.pk).update(created_at=written, updated_at=written)
        source.objects.create(
            kind="commerce.new_order", subject="Gone", text="x", deleted_at=written
        )
        source.objects.create(kind="commerce.order_note", subject="Commerce's", text="x")
        target.objects.create(kind="commerce.order_note", subject="The contract's", text="y")
        new = _at(AFTER)
        rows = {row.kind: row for row in new.get_model("notify", "EmailTemplate").objects.all()}
        assert set(rows) == {"commerce.order_paid", "commerce.order_note"}  # no deleted one
        paid = rows["commerce.order_paid"]
        assert (paid.pk, paid.subject, paid.text) == (moved.pk, "Paid", "Thanks")
        assert paid.created_at == written and paid.updated_at == written
        assert rows["commerce.order_note"].subject == "The contract's"  # its own edit wins
        assert "karni_commerce_emailtemplate" not in connection.introspection.table_names()
        back = _at(BEFORE)  # and back again
        restored = back.get_model("karni_commerce", "EmailTemplate").objects.get(
            kind="commerce.order_paid"
        )
        assert restored.subject == "Paid"
    finally:
        _leave_at_latest()


def test_without_notify_an_edited_email_stops_the_migration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from karni.notify import adopt

    try:
        old = _at(BEFORE)
        source = old.get_model("karni_commerce", "EmailTemplate")
        monkeypatch.setattr(adopt, "installed", lambda: False)

        class Editor:
            connection: Any = connection

        assert MOVE.forwards(old, Editor()) is None  # nothing edited: nothing to lose
        source.objects.create(kind="commerce.order_paid", subject="Paid", text="Thanks")
        with pytest.raises(KarniError) as stopped:
            MOVE.forwards(old, Editor())
        assert stopped.value.code == "E446"
        assert adopt.return_edited_emails(old, Editor(), MOVE.SOURCE) == 0
    finally:
        monkeypatch.undo()
        _leave_at_latest()
