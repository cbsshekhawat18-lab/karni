"""``karni migrate`` — apply database migrations through the project interpreter."""

from __future__ import annotations

import typer

from karni_cli import project as project_mod
from karni_cli.project import require_project


def migrate(
    args: list[str] | None = typer.Argument(
        None, help="Passed to manage.py migrate: [app_label] [migration_name] --plan --fake …"
    ),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """Apply migrations — wraps `manage.py migrate [ARGS]`."""
    project = require_project()
    proc = project_mod.run_manage(
        project,
        ["migrate", *(args or [])],
        docker=docker,
        service=service,
        capture=False,
        database="connect",
    )
    raise typer.Exit(proc.returncode)
