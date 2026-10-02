"""``karni shell`` — an interactive Django shell in the project environment."""

from __future__ import annotations

import typer

from karni_cli import project as project_mod
from karni_cli.project import require_project


def shell(
    args: list[str] | None = typer.Argument(
        None, help="Passed to manage.py shell: -c CODE, -i ipython …"
    ),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """Open a Django shell — wraps `manage.py shell [ARGS]`."""
    project = require_project()
    proc = project_mod.run_manage(
        project,
        ["shell", *(args or [])],
        docker=docker,
        service=service,
        capture=False,
        interactive=True,
    )
    raise typer.Exit(proc.returncode)
