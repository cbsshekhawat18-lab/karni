"""``karni createsuperuser`` — create an admin user (prompts unless --noinput)."""

from __future__ import annotations

import typer

from karni_cli import project as project_mod
from karni_cli.project import require_project


def createsuperuser(
    args: list[str] | None = typer.Argument(
        None, help="Passed to manage.py createsuperuser: --email E, --noinput …"
    ),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """Create an admin user. It wraps `manage.py createsuperuser [ARGS]`."""
    project = require_project()
    proc = project_mod.run_manage(
        project,
        ["createsuperuser", *(args or [])],
        docker=docker,
        service=service,
        capture=False,
        interactive=True,
        database="connect",
    )
    raise typer.Exit(proc.returncode)
