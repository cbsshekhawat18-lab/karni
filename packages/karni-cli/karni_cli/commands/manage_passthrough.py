"""``karni manage`` — raw ``manage.py`` passthrough in the project environment.

The escape hatch for any Django/third-party management command without a
dedicated runner. Put ``--`` before arguments that clash with this command's
own options (``--docker``, ``--service``, ``--help``).
"""

from __future__ import annotations

import typer

from karni_cli import project as project_mod
from karni_cli.project import require_project


def manage(
    args: list[str] | None = typer.Argument(
        None, help="The manage.py command and its arguments, e.g. `showmigrations events`."
    ),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """Run any management command — wraps `manage.py ARGS` (raw passthrough)."""
    project = require_project()
    proc = project_mod.run_manage(
        project, list(args or []), docker=docker, service=service, capture=False, interactive=True
    )
    raise typer.Exit(proc.returncode)
