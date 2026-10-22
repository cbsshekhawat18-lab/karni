"""``karni queries ENDPOINT --as USER`` — every SQL query an endpoint runs, and why.

Wraps ``manage.py karni_queries`` (:mod:`karni.api.diagnose`), run in the
project's interpreter: one request in-process (writes rolled back), every
statement with the stack that issued it, the repeated ones grouped by cause
(the serializer field, the relation, why the optimiser did not fetch it) and
the fix. ``--json`` for agents.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from karni_cli import project as project_mod
from karni_cli.project import CliError, require_project

_UNKNOWN = "Unknown command: 'karni_queries'"


def queries_args(
    endpoint: str,
    user: str | None,
    method: str,
    data: str | None,
    as_json: bool,
    explain: bool,
    every: bool,
) -> list[str]:
    """The ``manage.py`` argv for one ``karni queries`` call."""
    args = ["karni_queries", endpoint, "--method", method]
    if user:
        args += ["--as", user]
    if data is not None:
        args += ["--data", data]
    args += [
        flag for flag, on in (("--json", as_json), ("--explain", explain), ("--all", every)) if on
    ]
    return args


def run_queries(
    project: Path,
    args: list[str],
    *,
    docker: bool | None = None,
    service: str = "django",
) -> tuple[int, str, str]:
    """Run ``manage.py karni_queries``; ``(exit code, stdout, stderr)``.

    :raises CliError: ``C341`` when the project's karni predates the command.
    """
    proc = project_mod.run_manage(project, args, docker=docker, service=service, database="connect")
    if proc.returncode != 0 and _UNKNOWN in (proc.stderr or ""):
        raise CliError(
            "The project's karni has no karni_queries command (it predates karni queries). "
            "Upgrade karni in the project: pip install -U karni.",
            code="C341",
        )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def queries(
    endpoint: str = typer.Argument(
        ...,
        help="A path (/api/events/?page=2), a resource (events, events/<id>) or a viewset "
        "(EventViewSet, EventViewSet.retrieve).",
    ),
    user: str | None = typer.Option(
        None, "--as", help="The user: email, username or primary key (default: anonymous)."
    ),
    method: str = typer.Option("GET", "--method", help="HTTP method."),
    data: str | None = typer.Option(
        None, "--data", help="JSON request body (the request's writes are rolled back)."
    ),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
    explain: bool = typer.Option(
        False, "--explain", help="Add EXPLAIN plans for the slowest queries."
    ),
    every: bool = typer.Option(False, "--all", help="List every statement, not only repeats."),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """Run one endpoint in-process as a user: query count and time, repeated queries grouped
    by cause (field, relation, why the optimiser did not fetch it) and the fix — wraps
    `manage.py karni_queries`."""
    project = require_project()
    args = queries_args(endpoint, user, method, data, as_json, explain, every)
    code, out, err = run_queries(project, args, docker=docker, service=service)
    if out:
        typer.echo(out.rstrip("\n"))
    if err:
        sys.stderr.write(err)
    raise typer.Exit(code)
