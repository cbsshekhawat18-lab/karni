"""``karni upgrade`` — apply mechanical migrations between Karni versions."""

from __future__ import annotations

import subprocess

import typer

from karni_cli import project as project_mod
from karni_cli.project import CliError, require_project, venv_python
from karni_cli.upgrades import UPGRADES, applicable


def _installed_version(project, docker: bool | None, service: str) -> str:
    code = "import karni; print(karni.__version__)"
    mode = project_mod.resolve_execution(project, docker, service)
    if mode == "venv":
        cmd = [str(venv_python(project)), "-c", code]
    else:
        cmd = ["docker", "compose", "exec", "-T", service, "python", "-c", code]
    proc = subprocess.run(cmd, cwd=project, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise CliError(
            "Could not determine the installed karni version "
            f"(exit {proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout.strip()


def upgrade(
    list_only: bool = typer.Option(False, "--list", help="List registered migrations"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    if not UPGRADES:
        typer.echo("Already current — no mechanical migrations registered.")
        return
    if list_only:
        for u in UPGRADES:
            typer.echo(f"{u.from_spec} -> {u.to_version}: {u.description}")
        return

    project = require_project()
    installed = _installed_version(project, docker, service)
    todo = applicable(installed)
    if not todo:
        typer.echo(f"karni {installed}: no applicable migrations.")
        return
    for u in todo:
        changed = u.apply(project, dry_run)
        verb = "would change" if dry_run else "changed"
        typer.echo(f"-> {u.to_version} ({u.description}): {verb} {len(changed)} file(s)")
        for path in changed:
            typer.echo(f"   {path}")
