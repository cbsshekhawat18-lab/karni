"""``karni schedule list|run`` — the merged beat schedules (``manage.py karni_schedules``)."""

from __future__ import annotations

import typer

from karni_cli import project as project_mod
from karni_cli.project import require_project

schedule_app = typer.Typer(
    help="Celery beat schedules — wraps `manage.py karni_schedules`.",
    no_args_is_help=True,
)


@schedule_app.command("list")
def list_schedules(
    as_json: bool = typer.Option(False, "--json", help="Print the schedules as a JSON list."),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """List every schedule: name, task, timing, source — wraps `manage.py karni_schedules`."""
    project = require_project()
    args = ["karni_schedules", *(["--json"] if as_json else [])]
    proc = project_mod.run_manage(project, args, docker=docker, service=service, capture=False)
    raise typer.Exit(proc.returncode)


@schedule_app.command("run")
def run_schedule(
    name: str = typer.Argument(..., help="The schedule name (see `karni schedule list`)."),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """Run one schedule's task now, synchronously — wraps `manage.py karni_schedules --run NAME`."""
    project = require_project()
    proc = project_mod.run_manage(
        project, ["karni_schedules", "--run", name], docker=docker, service=service, capture=False
    )
    raise typer.Exit(proc.returncode)
