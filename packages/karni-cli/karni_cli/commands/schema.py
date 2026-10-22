"""``karni schema`` — columns, constraints and indexes per model, and why (``manage.py karni_schema``)."""

from __future__ import annotations

import typer

from karni_cli import project as project_mod
from karni_cli.project import CliError, require_project


def schema(
    labels: list[str] | None = typer.Argument(
        None, help="App labels or app.Model (default: every model of your own apps)."
    ),
    as_json: bool = typer.Option(False, "--json", help="Print the report as JSON (for agents)."),
    no_db: bool = typer.Option(
        False, "--no-db", help="Report the declarations only; do not read the database."
    ),
    database: str = typer.Option("default", "--database", help="Database alias to describe."),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """Every column, constraint and index, and the declaration behind each — wraps `manage.py karni_schema`.

    Per model: column types and CHECKs, unique constraints (partial on
    soft-deletable models), indexes (Django's FK indexes, Karni's GIN/BRIN),
    each with why it exists and whether the database has it; the columns
    viewsets search, filter or order by, with the index serving each.

    Example: karni schema events --json
    """
    project = require_project()
    args = [
        "karni_schema",
        *(labels or []),
        *(["--json"] if as_json else []),
        *(["--no-db"] if no_db else []),
        "--database",
        database,
    ]
    proc = project_mod.run_manage(
        project,
        args,
        docker=docker,
        service=service,
        capture=True,
        database="load" if no_db else "connect",
    )
    if proc.returncode != 0 and "Unknown command" in (proc.stderr or ""):
        raise CliError(
            "The project's karni has no karni_schema command (it arrived with the typed field "
            "layer). Upgrade the project's karni (`karni upgrade`, then reinstall), or run "
            "`karni doctor` to see which karni the project uses.",
            code="C361",
        )
    if proc.stdout:
        typer.echo(proc.stdout, nl=not proc.stdout.endswith("\n"))
    if proc.stderr:
        typer.echo(proc.stderr, err=True, nl=not proc.stderr.endswith("\n"))
    raise typer.Exit(proc.returncode)
