"""``karni routes`` — every URL the project serves (``manage.py karni_routes``)."""

from __future__ import annotations

import typer

from karni_cli import project as project_mod
from karni_cli.project import require_project


def routes(
    as_json: bool = typer.Option(False, "--json", help="Print the routes as a JSON list."),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """List every URL with its methods, name, view, model and access.

    It wraps `manage.py karni_routes`.
    """
    project = require_project()
    args = ["karni_routes", *(["--json"] if as_json else [])]
    proc = project_mod.run_manage(project, args, docker=docker, service=service, capture=False)
    raise typer.Exit(proc.returncode)
