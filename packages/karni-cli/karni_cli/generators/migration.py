"""``karni make migration [name]`` — ``manage.py makemigrations`` through the project interpreter.

The only generator that needs Django: it runs the project's own
``makemigrations`` (``.venv``, else the running compose service — see
:mod:`karni_cli.project`), streaming its output and exit code.
"""

from __future__ import annotations

from pathlib import Path

import typer

from karni_cli import project as project_mod
from karni_cli.generators.core import APP_OPTION, DRY_RUN_OPTION, Workspace, resolve_app
from karni_cli.project import require_project

NAME = "migration"
SUMMARY = "Create migrations: wraps manage.py makemigrations [app] [--name] [--empty]."


def makemigrations_args(
    app_label: str | None, name: str | None, *, empty: bool, dry_run: bool
) -> list[str]:
    args = ["makemigrations"]
    if app_label:
        args.append(app_label)
    if name:
        args += ["--name", name]
    if empty:
        args.append("--empty")
    if dry_run:
        args.append("--dry-run")
    return args


def run(
    project: Path,
    app_label: str | None,
    name: str | None = None,
    *,
    empty: bool = False,
    dry_run: bool = False,
    docker: bool | None = None,
    service: str = "django",
) -> int:
    """Run makemigrations in the project environment; returns its exit code."""
    proc = project_mod.run_manage(
        project,
        makemigrations_args(app_label, name, empty=empty, dry_run=dry_run),
        docker=docker,
        service=service,
        capture=False,
    )
    return proc.returncode


def command(
    name: str | None = typer.Argument(
        None, help="Migration name (makemigrations --name), e.g. add_event_capacity."
    ),
    empty: bool = typer.Option(
        False, "--empty", help="An empty migration to fill in (data migrations); needs one app."
    ),
    app: str | None = APP_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """Create migrations — wraps `manage.py makemigrations [APP] [--name NAME] [--empty]`.

    Without --app every app with model changes gets a migration; --empty
    (a data migration) targets one app: --app, else the only local app.
    --dry-run is makemigrations' own (prints, writes nothing).
    """
    project = require_project()
    label = None
    if app is not None or empty:
        label = resolve_app(Workspace(project), app).label
    raise typer.Exit(
        run(project, label, name, empty=empty, dry_run=dry_run, docker=docker, service=service)
    )
