"""``karni beat`` — Celery beat (the scheduler) through the project interpreter.

Beat merges every ``<app>/schedules.py`` declaration into its schedule at
startup (``karni.schedule``); list them with ``karni schedule list``. With
the docker compose stack up, a ``beat`` service already runs — run only one.
"""

from __future__ import annotations

import typer

from karni_cli import project as project_mod
from karni_cli.commands.worker import celery_args
from karni_cli.project import require_project


def beat(
    args: list[str] | None = typer.Argument(None, help="Passed to celery beat."),
    celery_app: str = typer.Option(
        "config", "--app", "-A", envvar="KARNI_CELERY_APP", help="Celery app module."
    ),
    loglevel: str = typer.Option("info", "--loglevel", "-l"),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """Run Celery beat — wraps `python -m celery -A config beat -l info [ARGS]`."""
    project = require_project()
    proc = project_mod.run_python(
        project,
        celery_args(celery_app, "beat", loglevel, args),
        docker=docker,
        service=service,
        capture=False,
        interactive=True,
    )
    raise typer.Exit(proc.returncode)
