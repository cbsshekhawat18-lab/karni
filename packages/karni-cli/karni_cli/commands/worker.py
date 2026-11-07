"""``karni worker`` — a Celery worker through the project interpreter.

With the docker compose stack up, a ``worker`` service already runs; this
command is for local (``.venv``) development or a one-off extra worker.

A host worker on macOS runs Celery's ``threads`` pool unless ``--pool`` (or
``-P`` among the arguments) picks another. Celery's default ``prefork`` pool
fails every task there: billiard 4.3 starts the pool's processes with
``spawn`` on macOS, and Celery only rebuilds its task-tracing state in a
spawned process on Windows, so each task fails in ``fast_trace_task`` with
"not enough values to unpack". ``threads`` rather than ``solo``: the worker
keeps answering ``celery inspect`` and the health check's ping while a task
runs, and a slow task does not hold up the others, as with ``prefork`` in
production. Docker runs Linux and keeps Celery's default.
"""

from __future__ import annotations

import sys
from typing import Final

import typer

from karni_cli import project as project_mod
from karni_cli.project import require_project

#: Celery's pool names (``celery worker --pool``).
POOLS: Final = ("prefork", "threads", "solo", "eventlet", "gevent", "processes", "custom")

#: The pool a host worker on macOS runs when none is given.
MACOS_POOL: Final = "threads"


def celery_args(celery_app: str, role: str, loglevel: str, extra: list[str] | None) -> list[str]:
    """``-m celery -A <app> <role> -l <level> [extra]`` (shared with ``karni beat``)."""
    return ["-m", "celery", "-A", celery_app, role, "-l", loglevel, *(extra or [])]


def _known_pool(value: str | None) -> str | None:
    if value is not None and value not in POOLS:
        raise typer.BadParameter(f"{value!r} is not a Celery pool. Use one of: {', '.join(POOLS)}.")
    return value


def _names_pool(args: list[str]) -> bool:
    return any(a == "-P" or a.startswith(("--pool", "-P")) for a in args)


def pool_args(
    extra: list[str] | None,
    *,
    pool: str | None = None,
    on_host: bool = True,
    platform: str | None = None,
) -> list[str]:
    """The worker's arguments with its pool: ``pool`` when given, else the host default.

    ``--pool=<pool>`` goes last, so it wins over a ``-P`` among ``extra``. With
    no ``pool``, a pool in ``extra`` is kept, and a host worker on macOS gets
    :data:`MACOS_POOL`. Anywhere else Celery picks (``prefork``).
    """
    args = list(extra or [])
    if pool:
        return [*args, f"--pool={pool}"]
    if not on_host or (platform or sys.platform) != "darwin" or _names_pool(args):
        return args
    return [*args, f"--pool={MACOS_POOL}"]


def worker(
    args: list[str] | None = typer.Argument(
        None, help="Passed to celery worker: -Q QUEUES, --concurrency N …"
    ),
    celery_app: str = typer.Option(
        "config", "--app", "-A", envvar="KARNI_CELERY_APP", help="Celery app module."
    ),
    loglevel: str = typer.Option("info", "--loglevel", "-l"),
    pool: str | None = typer.Option(
        None,
        "--pool",
        "-P",
        callback=_known_pool,
        help=(
            "Celery's pool: threads, solo or prefork (or eventlet, gevent). "
            "Default: threads for a worker on a Mac, else Celery's prefork."
        ),
    ),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """Run a Celery worker. It wraps `python -m celery -A config worker -l info [ARGS]`.

    A worker on a Mac runs the threads pool (Celery's prefork pool fails every task there).
    """
    project = require_project()
    on_host = docker is not True and project_mod.venv_python(project) is not None
    extra = pool_args(args, pool=pool, on_host=on_host)
    if on_host and sys.platform == "darwin" and pool == "prefork":
        typer.echo(
            "karni worker: the prefork pool fails every task on macOS (billiard starts its "
            "processes with spawn there). --pool threads or --pool solo run them.",
            err=True,
        )
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
