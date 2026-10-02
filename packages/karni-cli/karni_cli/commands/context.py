"""``karni context`` — the token-efficiency mechanism.

Backend inventory comes from ``manage.py karni_context``; COMPONENTS/HOOKS
come from @karni/ui's build-generated dist/manifest.json. Absent manifest →
those lines are omitted entirely (never stale, never guessed).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from karni_cli import project as project_mod
from karni_cli.project import require_project


def find_manifest(project: Path, explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit if explicit.is_file() else None
    for base in (project / "frontend", project):
        candidate = base / "node_modules" / "@karni" / "ui" / "dist" / "manifest.json"
        if candidate.is_file():
            return candidate
    return None


def manifest_lines(manifest_path: Path) -> list[str]:
    try:
        data = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    lines: list[str] = []
    if data.get("components"):
        lines.append("COMPONENTS: " + " ".join(sorted(data["components"])))
    if data.get("hooks"):
        lines.append("HOOKS: " + " ".join(sorted(data["hooks"])))
    return lines


def assemble(backend_output: str, ui_lines: list[str]) -> str:
    """Merge UI lines into the backend sections, keeping the documented order
    (MODELS, VIEWSETS, COMPONENTS, HOOKS, MODULES, BASES)."""
    sections = [line for line in backend_output.split("\n") if line.strip()]
    insert_at = next(
        (i for i, line in enumerate(sections) if line.startswith(("MODULES:", "BASES:"))),
        len(sections),
    )
    sections[insert_at:insert_at] = ui_lines
    return "\n".join(sections)


def context(
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
    manifest: Path | None = typer.Option(None, "--manifest", help="Explicit manifest.json path"),
) -> None:
    project = require_project()
    proc = project_mod.run_manage(project, ["karni_context"], docker=docker, service=service)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        raise typer.Exit(proc.returncode)

    found = find_manifest(project, manifest)
    ui_lines = manifest_lines(found) if found else []
    typer.echo(assemble(proc.stdout, ui_lines))
