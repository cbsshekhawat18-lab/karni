"""``karni make model --external``: a model over an existing table or view (experimental).

The project's ``manage.py karni_inspect`` reads the columns; here it is
replaced by answers it gives on SQLite and on PostgreSQL (packages/karni's
``tests/test_external.py`` runs the real command on both databases, and
feeds its answer through :func:`karni_cli.generators.external.render`).
"""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from karni_cli import project as project_mod

from .test_make import fails, ok, project  # noqa: F401 - the project fixture

MARKER = "karni-inspect: "

SQLITE: dict[str, Any] = {
    "status": "ok",
    "db_table": "ext_target",
    "database": "default",
    "vendor": "sqlite",
    "kind": "table",
    "fields": [
        {"name": "id", "type": "AutoField", "params": {"primary_key": True}, "notes": []},
        {"name": "region", "type": "CharField", "params": {"max_length": 10}, "notes": []},
        {"name": "year", "type": "IntegerField", "params": {}, "notes": []},
        {
            "name": "amount",
            "type": "DecimalField",
            "params": {"max_digits": 10, "decimal_places": 5},
            "notes": [
                (
                    "max_digits and decimal_places have been guessed, as this database handles "
                    "decimal fields as float"
                )
            ],
        },
    ],
    "notes": [],
}

POSTGRES: dict[str, Any] = {
    "status": "ok",
    "db_table": 'reporting"."sales',
    "database": "warehouse",
    "vendor": "postgresql",
    "kind": "view",
    "fields": [
        {"name": "id", "type": "IntegerField", "params": {"primary_key": True}, "notes": []},
        {
            "name": "region_code",
            "type": "CharField",
            "params": {"db_column": "RegionCode", "max_length": 10, "blank": True, "null": True},
            "notes": ["Field name made lowercase."],
        },
        {
            "name": "amount",
            "type": "DecimalField",
            "params": {"max_digits": 12, "decimal_places": 2},
            "notes": [],
        },
    ],
    "notes": [
        (
            "The view has no primary key, so id is the primary key. Django needs one column "
            "whose values are unique: move primary_key=True if id is not that column."
        )
    ],
}


def _answer(monkeypatch: pytest.MonkeyPatch, answer: dict[str, Any]) -> list[list[str]]:
    calls: list[list[str]] = []

    def run_manage(root: Path, args: list[str], **kwargs: Any) -> Any:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=MARKER + json.dumps(answer), stderr="")

    monkeypatch.setattr(project_mod, "run_manage", run_manage)
    return calls


def test_a_sqlite_table_becomes_a_writable_external_model(
    project: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _answer(monkeypatch, SQLITE)
    ok("make", "app", "reports")
    result = ok(
        "make", "model", "Target", "--app", "reports", "--external", "--table", "ext_target",
        "--writable",
    )  # fmt: skip
    assert calls == [["karni_inspect", "ext_target", "--database", "default"]]
    source = (project / "reports" / "models.py").read_text()
    ast.parse(source)
    assert "from django.db import models" in source
    assert "class Target(models.Model):" in source
    assert "    id = models.AutoField(primary_key=True)\n" in source
    assert "    region = models.CharField(max_length=10)\n" in source
    assert "    # max_digits and decimal_places have been guessed" in source
    assert '    class Meta:\n        managed = False\n        db_table = "ext_target"\n' in source
    assert "    class Karni:\n        external = True\n        writable = True\n" in source
    assert "database =" not in source
    assert "        return str(self.region)" in source
    viewsets = (project / "reports" / "viewsets.py").read_text()
    assert "class TargetViewSet(BaseViewSet):" in viewsets and "access = Granted()" in viewsets
    assert "read and write" in result.output
    assert "records the model with managed=False" in result.output


def test_a_postgres_schema_table_on_another_database(
    project: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _answer(monkeypatch, POSTGRES)
    ok("make", "app", "reports")
    result = ok(
        "make", "model", "Sale", "--app", "reports", "--external", "--table", "reporting.sales",
        "--database", "warehouse", "--access", "staff", "--order", "-amount",
    )  # fmt: skip
    assert calls == [["karni_inspect", "reporting.sales", "--database", "warehouse"]]
    source = (project / "reports" / "models.py").read_text()
    ast.parse(source)
    assert "db_table = 'reporting\".\"sales'" in source
    assert 'ordering = ["-amount"]' in source
    assert '        external = True\n        database = "warehouse"\n' in source
    assert "writable" not in source
    assert "    # The view has no primary key, so id is the primary key." in source
    assert "    # Field name made lowercase.\n" in source
    assert (
        "    region_code = models.CharField(\n"
        '        db_column="RegionCode", max_length=10, blank=True, null=True\n'
        "    )\n"
    ) in source
    assert "        return str(self.region_code)" in source
    assert "read-only" in result.output and "note: The view has no primary key" in result.output
    assert "access = Access(" in (project / "reports" / "viewsets.py").read_text()


@pytest.mark.parametrize(
    ("answer", "code", "text"),
    [
        ({"status": "unreachable", "database": "default", "error": "refused"}, "C140", "refused"),
        (
            {"status": "unknown-alias", "database": "x", "aliases": ["default"]},
            "C140",
            "no such alias",
        ),
        ({"status": "missing", "database": "default", "db_table": "sales"}, "C141", "no table"),
        (
            {"status": "no-schemas", "database": "default", "vendor": "sqlite", "db_table": "a"},
            "C141",
            "sqlite",
        ),
    ],
)
def test_the_database_must_answer_and_hold_the_table(
    project: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    answer: dict[str, Any],
    code: str,
    text: str,
) -> None:
    _answer(monkeypatch, answer)
    ok("make", "app", "reports")
    message = fails(
        "make", "model", "Sale", "--app", "reports", "--external", "--table", "sales", match=code
    )
    assert text in message
    assert "class Sale" not in (project / "reports" / "models.py").read_text()


def test_an_old_karni_without_the_command_is_named(
    project: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        project_mod,
        "run_manage",
        lambda *a, **k: subprocess.CompletedProcess(
            [], 1, stdout="", stderr="Unknown command: 'karni_inspect'"
        ),
    )
    ok("make", "app", "reports")
    message = fails(
        "make", "model", "Sale", "--app", "reports", "--external", "--table", "sales", match="C140"
    )
    assert "Unknown command" in message and "upgrade" in message


@pytest.mark.parametrize(
    ("args", "text"),
    [
        (("--table", "sales"), "add --external"),
        (("--writable",), "add --external"),
        (("--external",), "needs --table"),
        (("--external", "--table", "sales", "title:str"), "leave out title:str"),
        (("--external", "--table", "sales", "--key", "id"), "--key"),
    ],
)
def test_options_that_do_not_go_together(
    project: Path,  # noqa: F811
    args: tuple[str, ...],
    text: str,
) -> None:
    ok("make", "app", "reports")
    message = fails("make", "model", "Sale", "--app", "reports", *args, match="C142")
    assert text in message
