"""``karni worker`` — a Celery worker through the project interpreter.

With the docker compose stack up, a ``worker`` service already runs; this
command is for local (``.venv``) development or a one-off extra worker.
"""

from __future__ import annotations

import typer

from karni_cli import project as project_mod
from karni_cli.project import require_project


def celery_args(celery_app: str, role: str, loglevel: str, extra: list[str] | None) -> list[str]:
    """``-m celery -A <app> <role> -l <level> [extra]`` (shared with ``karni beat``)."""
    return ["-m", "celery", "-A", celery_app, role, "-l", loglevel, *(extra or [])]


def worker(
    args: list[str] | None = typer.Argument(
        None, help="Passed to celery worker: -Q QUEUES, --concurrency N …"
    ),
    celery_app: str = typer.Option(
        "config", "--app", "-A", envvar="KARNI_CELERY_APP", help="Celery app module."
    ),
    loglevel: str = typer.Option("info", "--loglevel", "-l"),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """Run a Celery worker — wraps `python -m celery -A config worker -l info [ARGS]`."""
    project = require_project()
    proc = project_mod.run_python(
        project,
        celery_args(celery_app, "worker", loglevel, args),
        docker=docker,
        service=service,
        capture=False,
        interactive=True,
    )
    raise typer.Exit(proc.returncode)
