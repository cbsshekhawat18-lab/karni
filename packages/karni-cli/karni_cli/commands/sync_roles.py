"""``karni sync-roles`` — reconcile the role tables with ``KARNI_ROLES`` (``manage.py karni_sync_roles``)."""

from __future__ import annotations

import typer

from karni_cli import project as project_mod
from karni_cli.project import require_project


def sync_roles(
    args: list[str] | None = typer.Argument(
        None, help="Passed to manage.py karni_sync_roles: --dry-run, --json."
    ),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """Create or update the roles KARNI_ROLES declares — wraps `manage.py karni_sync_roles [ARGS]`.

    Expands each role's grant patterns against every model and action into
    Role, Permission and RolePermission rows: creates what is missing,
    updates what changed, reports roles the database holds that the
    declaration no longer names, and never deletes. The same sync runs
    after every `karni migrate` (KARNI_ROLES_AUTOSYNC).

    Example: karni sync-roles --dry-run
    """
    project = require_project()
    proc = project_mod.run_manage(
        project,
        ["karni_sync_roles", *(args or [])],
        docker=docker,
        service=service,
        capture=False,
        database="connect",
    )
    raise typer.Exit(proc.returncode)
