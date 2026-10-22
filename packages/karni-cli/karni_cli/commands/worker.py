"""``karni worker`` — a Celery worker through the project interpreter.

With the docker compose stack up, a ``worker`` service already runs; this
command is for local (``.venv``) development or a one-off extra worker.
"""

from __future__ import annotations

import sys

import typer

from karni_cli import project as project_mod
from karni_cli.project import require_project


def celery_args(celery_app: str, role: str, loglevel: str, extra: list[str] | None) -> list[str]:
    """``-m celery -A <app> <role> -l <level> [extra]`` (shared with ``karni beat``)."""
    return ["-m", "celery", "-A", celery_app, role, "-l", loglevel, *(extra or [])]


def host_pool_args(extra: list[str] | None, platform: str | None = None) -> list[str]:
    """``--pool=solo`` for a host worker on macOS, unless the caller chose a pool.

    Celery's default prefork pool cannot run tasks on macOS (every task fails
    in ``fast_trace_task`` with "not enough values to unpack"); the solo pool
    does, and a development worker needs nothing more. Docker runs Linux and
    keeps the default.
    """
    args = list(extra or [])
    platform = platform or sys.platform
    if platform != "darwin" or any(a == "-P" or a.startswith(("--pool", "-P")) for a in args):
        return args
    return [*args, "--pool=solo"]


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
    """Run a Celery worker. It wraps `python -m celery -A config worker -l info [ARGS]`.

    A host worker on macOS gets `--pool=solo` (the prefork pool cannot run tasks there).
    """
    project = require_project()
    on_host = docker is not True and project_mod.venv_python(project) is not None
    extra = host_pool_args(args) if on_host else list(args or [])
    proc = project_mod.run_python(
        project,
        celery_args(celery_app, "worker", loglevel, extra),
        docker=docker,
        service=service,
        capture=False,
        interactive=True,
        database="load",
    )
    raise typer.Exit(proc.returncode)
