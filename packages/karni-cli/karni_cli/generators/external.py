"""``karni make model <Name> --external --table <[schema.]table>``: a model over an existing table.

Experimental. The table or view belongs to another system, so the model's
fields come from its columns: the project's ``manage.py karni_inspect``
reads them with Django's ``inspectdb`` machinery (field types, ``null``,
``max_length``, the primary key) and prints them as JSON, and this module
writes::

    class Sale(models.Model):
        id = models.IntegerField(primary_key=True)
        region = models.CharField(max_length=40)

        class Meta:
            managed = False
            db_table = 'reporting"."sales'

        class Karni:
            external = True
            database = "warehouse"   # with --database
            writable = True          # with --writable

``karni make model`` then writes the viewset with its ``access`` declaration,
as for any model. The database must answer (``C140``) and hold the table
(``C141``).
"""

from __future__ import annotations

import json
from typing import Any, Final

from karni_cli import project as project_mod
from karni_cli.generators.core import App, Workspace
from karni_cli.generators.introspect import models_file
from karni_cli.generators.naming import require_pascal
from karni_cli.generators.pysource import (
    Import,
    call,
    comment,
    ensure_imports,
    pystr,
    replace_or_append,
)
from karni_cli.project import CliError

#: What ``manage.py karni_inspect`` prints before its JSON answer.
MARKER: Final = "karni-inspect: "
DEFAULT_DATABASE: Final = "default"

_TEXT: Final = frozenset({"CharField", "TextField", "SlugField", "EmailField", "URLField"})


def inspect(ws: Workspace, table: str, database: str) -> dict[str, Any]:
    """The columns of ``table`` as fields, from the project's ``manage.py karni_inspect``."""
    proc = project_mod.run_manage(
        ws.root, ["karni_inspect", table, "--database", database], capture=True
    )
    out = proc.stdout or ""
    line = next((row for row in out.splitlines() if row.startswith(MARKER)), None)
    if proc.returncode != 0 or line is None:
        detail = (proc.stderr or out).strip().splitlines()
        raise CliError(
            f"manage.py karni_inspect {table} --database {database} did not answer "
            f"({detail[-1] if detail else f'exit code {proc.returncode}'}). It comes with "
            "karni 0.4.1: upgrade the project's karni, and check that the settings load.",
            code="C140",
        )
    answer: dict[str, Any] = json.loads(line[len(MARKER) :])
    status = answer.get("status")
    if status == "unreachable":
        raise CliError(
            f"Database {database!r} did not answer ({answer.get('error')}). --external reads the "
            f"columns of {table} from it, so it must be reachable: start it or fix "
            f"DATABASES[{database!r}], then run the command again.",
            code="C140",
        )
    if status == "unknown-alias":
        known = ", ".join(answer.get("aliases") or []) or "none"
        raise CliError(
            f"--database {database}: no such alias in DATABASES (aliases: {known}).",
            code="C140",
        )
    if status == "missing":
        raise CliError(
            f"Database {database!r} has no table or view {table!r}. Check the name (schema.table "
            "for a PostgreSQL schema) and --database.",
            code="C141",
        )
    if status == "no-schemas":
        raise CliError(
            f"--table {table} names a schema, but database {database!r} is "
            f"{answer.get('vendor')}, which has none. Schemas are PostgreSQL's: pass the "
            "plain table name.",
            code="C141",
        )
    if status != "ok":
        raise CliError(f"manage.py karni_inspect answered {answer!r}.", code="C140")
    return answer


def _literal(value: Any) -> str:
    if isinstance(value, str):
        return pystr(value)
    return repr(value)


def render(
    model: str,
    answer: dict[str, Any],
    *,
    database: str,
    writable: bool,
    order: str | None,
    line_length: int,
) -> str:
    """The model class for ``answer`` (what :func:`inspect` returns)."""
    fields: list[dict[str, Any]] = list(answer.get("fields") or [])
    lines = [f"class {model}(models.Model):"]
    for note in answer.get("notes") or []:
        lines.append(comment(str(note), "    ", line_length))
    for field in fields:
        for note in field.get("notes") or []:
            lines.append(comment(str(note), "    ", line_length))
        args = [f"{key}={_literal(value)}" for key, value in (field.get("params") or {}).items()]
        lines.append(call(f"{field['name']} = models.{field['type']}", args, "    ", line_length))
    lines += ["", "    class Meta:", "        managed = False"]
    lines.append(f"        db_table = {pystr(str(answer['db_table']))}")
    if order is not None:
        name = order.lstrip("-")
        if name not in {field["name"] for field in fields}:
            names = ", ".join(field["name"] for field in fields) or "none"
            raise CliError(
                f"--order {order}: {name!r} is not a column of the table (fields: {names}).",
                code="C104",
            )
        lines.append(f"        ordering = [{pystr(order)}]")
    lines += ["", "    class Karni:", "        external = True"]
    if database != DEFAULT_DATABASE:
        lines.append(f"        database = {pystr(database)}")
    if writable:
        lines.append("        writable = True")
    shown = next(
        (
            field["name"]
            for field in fields
            if field.get("type") in _TEXT and not (field.get("params") or {}).get("primary_key")
        ),
        None,
    )
    if shown is None:
        shown = next(
            (f["name"] for f in fields if (f.get("params") or {}).get("primary_key")), None
        )
    if shown is not None:
        lines += ["", "    def __str__(self) -> str:", f"        return str(self.{shown})"]
    return "\n".join(lines)


def plan(
    ws: Workspace,
    app: App,
    name: str,
    *,
    table: str,
    database: str | None,
    writable: bool,
    order: str | None = None,
) -> str:
    """Plan the external model in ``<app>/models.py`` from the table. Returns the class name."""
    model = require_pascal(name, "Model name")
    alias = database or DEFAULT_DATABASE
    answer = inspect(ws, table, alias)
    path = models_file(ws, app)
    rel = ws.rel(path)
    block = render(
        model, answer, database=alias, writable=writable, order=order, line_length=ws.line_length
    )
    text = ws.read(path) or ""
    text = ensure_imports(ws, rel, text, [Import("django.db", "models")])
    ws.write(path, replace_or_append(ws, rel, text, model, block))
    kind = answer.get("kind", "table")
    ws.note(
        f"external: {model} reads the {kind} {answer['db_table']} of database {alias!r} "
        f"({'read and write' if writable else 'read-only: the API and the admin only read'})."
    )
    for note in answer.get("notes") or []:
        ws.note(f"note: {note}")
    return model


def check_options(
    *,
    external: bool,
    table: str | None,
    database: str | None,
    writable: bool,
    fields: list[str],
    key: str | None,
) -> None:
    """``C142`` for options that do not go together with (or without) ``--external``."""
    if not external:
        given = [
            flag
            for flag, value in (
                ("--table", table),
                ("--database", database),
                ("--writable", writable),
            )
            if value
        ]
        if given:
            raise CliError(
                f"{', '.join(given)} describe an external model: add --external (karni make model "
                "<Name> --external --table <[schema.]table>).",
                code="C142",
            )
        return
    if not table:
        raise CliError(
            "--external needs --table <[schema.]table>: the table or view whose columns become "
            "the fields.",
            code="C142",
        )
    if fields:
        raise CliError(
            f"--external takes its fields from {table}, so leave out {' '.join(fields)}.",
            code="C142",
        )
    if key and not writable:
        raise CliError(
            "--key sets the column imports match on, and imports never write a read-only "
            "external table. Leave it out, or add --writable.",
            code="C142",
        )
